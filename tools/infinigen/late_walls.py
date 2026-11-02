"""Post-realize wall finishing (hooked from kit_lighting, before architecture_textures):

    import late_walls; stats["late_walls"] = late_walls.apply(plans)

  * ROOM_BIGGLASS set: room_planner.big_glass.sweep(): wall-mounted items placed after the architecture pass that float in the glass opening are deleted
  * ROOM_MARKET_CEILING=1: dark-red timber beams, duct, tubes, track spots in the largest room; ROOM_SPREAD_PLANTS=2.0: floor plants closer than that move to free wall/corner spots; ROOM_WALL_BAND=r,g,b,z0,z1: a horizontal colour band on the walls (bisected, own material slot); ROOM_RUGS=1: woven rugs under the café table groups and in front of the counter; ROOM_PANEL_WALLS=r,g,b[,slat]: dark raised-panel wainscot look on every wall (or vertical 12 cm oak slats); ROOM_CHANDELIER=n: n crystal chandeliers over the café counter; ROOM_CEILING_RGB=r,g,b: one plain ceiling colour (the S10 dark warm brown); ROOM_TILE_WALL=<object prefix> (e.g. BackBarShelfFactory, which stands flush on its wall; CafeCounterFactory also works when the counter is near its back wall): white square tile on the wall behind it; ROOM_SMOOTH_FLOOR=1: one smooth light floor finish from the kit's floor_rgb;
    ROOM_WHITE_CEILING=1: grid removed + white ceiling; ROOM_FLAT_WALLS=1: every wall slot one plain paint from style_spec.wall_rgb (35% toward white)
  * ROOM_FEATURE_WALL=1 and style_spec['feature_rgb'] (linear): paint the wall BEHIND the exam table (the room wall plane facing the table on the side its back points to,
    nearest to it, >= 3 m2) in that colour -- exam-room S18's pale-blue accent wall. Plain Principled paint, so albedo/roughness GT read normally.
"""
from __future__ import annotations

import math
import os

import bmesh
import bpy
from mathutils import Vector, Matrix


def _room_of(o):
    return o.name.rsplit(".", 1)[0]


def paint_behind(prefix, mat):
    """Paint the room-wall plane behind the first object named <prefix>* in each room (its back = -front, front = +X) with `mat`; returns faces painted."""
    done = 0
    walls = [o for o in bpy.data.objects if o.type == "MESH" and o.name.endswith(".wall") and o.parent is None]
    for w in walls:
        pts = [w.matrix_world @ Vector(c) for c in w.bound_box]
        lo = Vector((min(p.x for p in pts), min(p.y for p in pts), 0)); hi = Vector((max(p.x for p in pts), max(p.y for p in pts), 0))
        tab = next((o for o in bpy.data.objects if o.name.startswith(prefix) and lo.x - 0.3 < o.matrix_world.translation.x < hi.x + 0.3
                    and lo.y - 0.3 < o.matrix_world.translation.y < hi.y + 0.3), None)
        if tab is None:
            continue
        T = tab.matrix_world.translation.copy(); T.z = 0
        back = -(tab.matrix_world.to_3x3() @ Vector((1, 0, 0))); back.z = 0; back.normalize()          # the factory's front is +X, the head end/back is -X
        mw3 = w.matrix_world.to_3x3(); groups = {}
        for p in w.data.polygons:
            n = (mw3 @ p.normal).normalized()
            if abs(n.z) > 0.2 or n.dot(back) > -0.7:                                                     # a vertical face looking back toward the table
                continue
            c = w.matrix_world @ p.center; dist = (c - T).dot(back)
            if dist < 0.05:
                continue
            groups.setdefault((round(n.x, 1), round(n.y, 1), round(c.dot(n), 1)), []).append((p.index, p.area, dist))
        cand = [(sum(d for _, _, d in g) / len(g), g) for g in groups.values() if sum(a for _, a, _ in g) >= 3.0]
        if not cand:
            continue
        faces = min(cand, key=lambda t: t[0])[1]
        if mat.name not in [m.name for m in w.data.materials if m]:
            w.data.materials.append(mat)
        idx = [m.name if m else "" for m in w.data.materials].index(mat.name)
        for i, _, _ in faces:
            w.data.polygons[i].material_index = idx
        done += len(faces)
        if os.environ.get("ROOM_SLAT_LED") == "1":                      # H2 r19: the headboard wall's oak slats are lit from above by a warm LED strip (an emissive bar + a wall-washing area light)
            dm_ = sum(d_ for _, _, d_ in faces) / len(faces); tang_ = Vector((-back.y, back.x, 0)); P_ = T + back * dm_ - back * 0.05
            zt_ = max((w.matrix_world @ Vector(c)).z for c in w.bound_box) - 0.25
            led_ = bpy.data.materials.get("ir_slat_led") or bpy.data.materials.new("ir_slat_led"); led_.use_nodes = True
            lb_ = led_.node_tree.nodes["Principled BSDF"]; lb_.inputs["Base Color"].default_value = (1, 0.8, 0.5, 1); lb_.inputs["Emission Color"].default_value = (1.0, 0.72, 0.38, 1); lb_.inputs["Emission Strength"].default_value = 8.0
            me_ = bpy.data.meshes.new("SlatLed"); bm_ = __import__("bmesh").new(); r_ = __import__("bmesh").ops.create_cube(bm_, size=1.0)
            __import__("bmesh").ops.scale(bm_, vec=(0.04, 2.6, 0.03), verts=r_["verts"]); bm_.to_mesh(me_); bm_.free(); me_.materials.append(led_)
            bo_ = bpy.data.objects.new(f"SlatLedStrip({w.name})", me_); bpy.context.scene.collection.objects.link(bo_)
            ang_ = math.atan2(tang_.y, tang_.x); bo_.rotation_euler = (0, 0, ang_ + math.pi / 2); bo_.location = (P_.x, P_.y, zt_)
            ld_ = bpy.data.lights.new(f"ir_slat_wash_{w.name}", "AREA"); ld_.shape = "RECTANGLE"; ld_.size = 2.6; ld_.size_y = 0.1; ld_.energy = 90.0; ld_.color = (1.0, 0.72, 0.4)
            lo_ = bpy.data.objects.new(f"PointLampFactory(slat).spawn_asset({w.name})", ld_); bpy.context.scene.collection.objects.link(lo_)
            lo_.location = (P_.x, P_.y, zt_ - 0.02); lo_.rotation_euler = ((back + Vector((0, 0, -0.45))).normalized().to_track_quat("-Z", "Y").to_euler())
    return done


def _paint_mat(rgb):
    mat = bpy.data.materials.get("ir_late_feature_wall") or bpy.data.materials.new("ir_late_feature_wall")
    mat.use_nodes = True; b = mat.node_tree.nodes["Principled BSDF"]; b.inputs["Base Color"].default_value = (*rgb, 1); b.inputs["Roughness"].default_value = 0.8
    b["weathered"] = True
    return mat


def _tile_mat(tile=0.125):
    """White square wall tile: a brick texture with square cells on (distance along the wall, z), grey grout."""
    mat = bpy.data.materials.get("ir_late_white_tile")
    if mat is not None:
        return mat
    mat = bpy.data.materials.new("ir_late_white_tile"); mat.use_nodes = True; N, L = mat.node_tree.nodes, mat.node_tree.links; b = N["Principled BSDF"]
    tc = N.new("ShaderNodeTexCoord"); sep = N.new("ShaderNodeSeparateXYZ"); L.new(tc.outputs["Object"], sep.inputs[0])
    s1 = N.new("ShaderNodeMath"); s1.operation = "ADD"; L.new(sep.outputs["X"], s1.inputs[0]); L.new(sep.outputs["Y"], s1.inputs[1])   # x + y: a vertical wall varies along only one of them
    cb = N.new("ShaderNodeCombineXYZ"); L.new(s1.outputs["Value"], cb.inputs["X"]); L.new(sep.outputs["Z"], cb.inputs["Y"])
    br = N.new("ShaderNodeTexBrick"); br.offset = 0.0; br.squash = 1.0
    br.inputs["Scale"].default_value = 1.0 / tile; br.inputs["Mortar Size"].default_value = 0.012; br.inputs["Brick Width"].default_value = 1.0; br.inputs["Row Height"].default_value = 1.0
    br.inputs["Color1"].default_value = (0.93, 0.93, 0.91, 1); br.inputs["Color2"].default_value = (0.9, 0.9, 0.88, 1); br.inputs["Mortar"].default_value = (0.62, 0.62, 0.6, 1)
    L.new(cb.outputs["Vector"], br.inputs["Vector"]); L.new(br.outputs["Color"], b.inputs["Base Color"]); b.inputs["Roughness"].default_value = 0.25
    b["weathered"] = True
    return mat


def _flat_room(o):
    """ROOM_FLAT_ONLY=warehouse,break-room_0/0 : ROOM_FLAT_WALLS / ROOM_SMOOTH_FLOOR only touch these rooms (a type prefix or a full room name); the others keep their scanned
    textures (user 10-18: J/M small rooms scored 5 on surface realism under the flat paint + smooth vinyl that suits the big hall)."""
    only = [x for x in os.environ.get("ROOM_FLAT_ONLY", "").split(",") if x]
    base = o.name.rsplit(".", 1)[0]
    return not only or any(base == x or base.startswith(x + "_") for x in only)


def smooth_floor(rgb, rough=None):
    """Replace every room floor's materials with one plain, smooth, light Principled finish (not weathered): the pale seamless vinyl / polished concrete of the refs."""
    rough = float(os.environ.get("ROOM_SMOOTH_FLOOR_ROUGH", "0.3")) if rough is None else rough           # env: duller (0.5) for warm polished concrete without the mirror look
    mat = bpy.data.materials.get("ir_late_floor_smooth") or bpy.data.materials.new("ir_late_floor_smooth")
    mat.use_nodes = True; b = mat.node_tree.nodes["Principled BSDF"]; b.inputs["Base Color"].default_value = (*rgb, 1); b.inputs["Roughness"].default_value = rough
    cw = os.environ.get("ROOM_SMOOTH_FLOOR_COAT")                                          # glossy epoxy / terrazzo (N2 r17: 'no specular streaks'): a clear coat over the base, so bare tubes and windows reflect as streaks
    if cw and "Coat Weight" in b.inputs:
        b.inputs["Coat Weight"].default_value = float(cw); b.inputs["Coat Roughness"].default_value = float(os.environ.get("ROOM_SMOOTH_FLOOR_COAT_ROUGH") or 0.04)
        for nm in ("Specular IOR Level", "Specular"):
            if nm in b.inputs:
                b.inputs[nm].default_value = 0.8
    if os.environ.get("ROOM_SMOOTH_FLOOR_MOTTLE") == "1" and "mottle" not in mat.get("tags", ""):      # worn polished concrete (market ref): patchy dark/light mottling in colour and roughness
        nt = mat.node_tree; N, Lk = nt.nodes, nt.links
        tc = N.new("ShaderNodeNewGeometry"); mp = N.new("ShaderNodeMapping"); mp.inputs["Scale"].default_value = (0.35, 0.35, 0.35)      # world position: the floor object's own coordinates are not in metres
        n1 = N.new("ShaderNodeTexNoise"); n1.inputs["Scale"].default_value = 3.0; n1.inputs["Detail"].default_value = 6.0; n1.inputs["Roughness"].default_value = 0.6
        cr = N.new("ShaderNodeValToRGB"); cr.color_ramp.elements[0].position = 0.35; cr.color_ramp.elements[1].position = 0.7
        cr.color_ramp.elements[0].color = (0.45, 0.45, 0.45, 1); cr.color_ramp.elements[1].color = (1.0, 1.0, 1.0, 1)
        mix = N.new("ShaderNodeMix"); mix.data_type = "RGBA"; mix.blend_type = "MULTIPLY"; mix.inputs[0].default_value = 1.0
        mx_in = lambda nm: next(x for x in mix.inputs if x.name == nm and x.type == "RGBA")      # a Mix node has float / vector / RGBA sockets with the same names: the first 'A' / 'B' / 'Result' is the float one
        mx_in("A").default_value = (*rgb, 1)
        rr = N.new("ShaderNodeMapRange"); rr.inputs["To Min"].default_value = rough * 0.7; rr.inputs["To Max"].default_value = min(1.0, rough * 1.9)
        Lk.new(tc.outputs["Position"], mp.inputs["Vector"]); Lk.new(mp.outputs["Vector"], n1.inputs["Vector"]); Lk.new(n1.outputs["Fac"], cr.inputs["Fac"])
        Lk.new(cr.outputs["Color"], mx_in("B")); Lk.new(next(x for x in mix.outputs if x.type == "RGBA"), b.inputs["Base Color"]); Lk.new(n1.outputs["Fac"], rr.inputs["Value"]); Lk.new(rr.outputs["Result"], b.inputs["Roughness"])
        mat["tags"] = "mottle"
    if os.environ.get("ROOM_FLOOR_WEAR") != "1":                 # ROOM_FLOOR_WEAR=1: let weather_pass / weather_variation dirty the floor (user 10-19: G/H/J/M floors "too clean, flat")
        b["weathered"] = True
    n = 0
    for o in bpy.data.objects:
        if o.type == "MESH" and o.name.endswith(".floor") and o.parent is None and _flat_room(o):
            for sl in o.material_slots:
                sl.material = mat
            n += 1
    return n


def white_ceiling(rgb=(0.9, 0.9, 0.88)):
    """Light ceiling grid and tiles: the dark grey T-bars (0.62 metallic) and the dim plaster read as a dark ceiling in a bright daylit clinic."""
    n = 0
    for o in list(bpy.data.objects):                                        # the raised 2 cm T-bars read as an exposed grid in a clinic: plain flat tiles instead (ROOM_WHITE_CEILING=grid keeps a white grid + the LED panels)
        if o.name.startswith("CeilingGridFactory") and os.environ.get("ROOM_WHITE_CEILING") != "grid":
            bpy.data.objects.remove(o, do_unlink=True); n += 1
    for m in bpy.data.materials:
        if m.use_nodes and m.name in ("ir_tbar",) and "Principled BSDF" in m.node_tree.nodes:
            b = m.node_tree.nodes["Principled BSDF"]; b.inputs["Base Color"].default_value = (*rgb, 1); b.inputs["Metallic"].default_value = 0.0; n += 1
    for o in bpy.data.objects:
        if o.type == "MESH" and o.name.endswith(".ceiling"):
            mat = bpy.data.materials.get("ir_late_ceiling") or bpy.data.materials.new("ir_late_ceiling"); mat.use_nodes = True
            b = mat.node_tree.nodes["Principled BSDF"]; b.inputs["Base Color"].default_value = (*rgb, 1); b.inputs["Roughness"].default_value = 0.7; b["weathered"] = True
            for sl in o.material_slots:
                sl.material = mat
            n += 1
    if os.environ.get("ROOM_WHITE_CEILING") == "slim":                       # O2 r10 refs: smooth white ceiling with SLIM recessed linear lights: each fluorescent bar becomes a 6 cm flush strip of the same length at the ceiling plane
        sm = bpy.data.materials.get("ir_late_slim_strip") or bpy.data.materials.new("ir_late_slim_strip"); sm.use_nodes = True; sb = sm.node_tree.nodes["Principled BSDF"]
        sb.inputs["Base Color"].default_value = (1, 1, 1, 1); sb.inputs["Emission Color"].default_value = (1.0, 0.97, 0.92, 1); sb.inputs["Emission Strength"].default_value = 6.0; sb["weathered"] = True
        for o in list(bpy.data.objects):
            if o.type != "MESH" or not o.name.startswith("LinearLedFactory") or o.name.startswith("LinearLedFactory(tile"):
                continue
            bb = [o.matrix_world @ Vector(c) for c in o.bound_box]
            xs, ys, zs = [p.x for p in bb], [p.y for p in bb], [p.z for p in bb]
            lx, ly = max(xs) - min(xs), max(ys) - min(ys)
            if max(lx, ly) < 0.4:
                continue
            cx, cy, zt = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2, max(zs)
            sz = (lx, 0.06, 0.012) if lx >= ly else (0.06, ly, 0.012)
            bm = bmesh.new(); bmesh.ops.create_cube(bm, size=1.0); bmesh.ops.scale(bm, vec=sz, verts=bm.verts); bmesh.ops.translate(bm, vec=(cx, cy, zt - 0.006), verts=bm.verts)
            me = bpy.data.meshes.new("slimled"); bm.to_mesh(me); bm.free(); me.materials.append(sm)
            t = bpy.data.objects.new(f"LinearLedFactory(slim_{n}).spawn_asset(0)", me); bpy.context.scene.collection.objects.link(t)
            bpy.data.objects.remove(o, do_unlink=True); n += 1
    if os.environ.get("ROOM_WHITE_CEILING") == "grid":                       # tile ceiling: 600 mm square LED panels (emissive tile + soft area light) in place of the linear troffers
        for o in list(bpy.data.objects):
            if o.name.startswith("LinearLedFactory") or (o.type == "LIGHT" and o.name.startswith("PointLampFactory(led)")):
                bpy.data.objects.remove(o, do_unlink=True); n += 1
        for cl in [o for o in bpy.data.objects if o.type == "MESH" and o.name.endswith(".ceiling")]:      # every room's ceiling, tiles only under its own footprint (floor C r17: only the first room got tiles, the open office stayed at mean-L 12)
            bb = [cl.matrix_world @ Vector(c) for c in cl.bound_box]; x0, x1, y0, y1, zc = min(p.x for p in bb), max(p.x for p in bb), min(p.y for p in bb), max(p.y for p in bb), max(p.z for p in bb)
            pm = bpy.data.materials.get("ir_late_led_tile") or bpy.data.materials.new("ir_late_led_tile"); pm.use_nodes = True; pb = pm.node_tree.nodes["Principled BSDF"]
            pb.inputs["Base Color"].default_value = (1, 1, 1, 1); pb.inputs["Emission Color"].default_value = (1.0, 0.97, 0.92, 1); pb.inputs["Emission Strength"].default_value = 5.0; pb["weathered"] = True
            nx, ny = max(1, int((x1 - x0) / 2.4)), max(1, int((y1 - y0) / 2.4))
            for i in range(nx):
                for j in range(ny):
                    cx, cy = x0 + (i + 0.5) * (x1 - x0) / nx, y0 + (j + 0.5) * (y1 - y0) / ny
                    cx, cy = round((cx - x0) / 0.6) * 0.6 + x0, round((cy - y0) / 0.6) * 0.6 + y0           # on the 600 mm grid
                    mi = cl.matrix_world.inverted()
                    if not cl.ray_cast(mi @ Vector((cx, cy, zc - 1.0)), (mi.to_3x3() @ Vector((0, 0, 1))).normalized())[0]:
                        continue
                    bm = bmesh.new(); bmesh.ops.create_cube(bm, size=1.0); bmesh.ops.scale(bm, vec=(0.58, 0.58, 0.02), verts=bm.verts)
                    me = bpy.data.meshes.new("ledtile"); bm.to_mesh(me); bm.free(); me.materials.append(pm)
                    t = bpy.data.objects.new(f"LinearLedFactory(tile_{i}_{j}).spawn_asset(0)", me); bpy.context.scene.collection.objects.link(t); t.location = (cx, cy, zc - 0.02)
                    ld = bpy.data.lights.new(f"ir_led_tile_{i}_{j}", "AREA"); ld.shape = "SQUARE"; ld.size = 0.58; ld.energy = 60.0 * float(os.environ.get("CEILING_LED_POWER", "1.0")); ld.color = (1.0, 0.97, 0.92)
                    lo = bpy.data.objects.new(f"PointLampFactory(led).spawn_asset(tile_{i}_{j})", ld); bpy.context.scene.collection.objects.link(lo); lo.location = (cx, cy, zc - 0.05); lo.rotation_euler = (math.pi, 0, 0)
                    n += 1
    return n


def flat_walls(rgb):
    """Every room wall slot -> one plain paint (no scan mottling); the painted accent faces of this module keep their own material."""
    mat = bpy.data.materials.get("ir_late_wall_flat") or bpy.data.materials.new("ir_late_wall_flat")
    mat.use_nodes = True; b = mat.node_tree.nodes["Principled BSDF"]; b.inputs["Base Color"].default_value = (*rgb, 1); b.inputs["Roughness"].default_value = 0.75; b["weathered"] = True
    n = 0
    for o in bpy.data.objects:
        if o.type == "MESH" and o.name.endswith(".wall") and o.parent is None and _flat_room(o):
            for sl in o.material_slots:
                if sl.material and not sl.material.name.startswith("ir_late_"):
                    sl.material = mat; n += 1
    return n


def dental_light():
    """A ceiling-mounted operatory light (generated prop DentalCeilingLight) over every DentalChairFactory: the head hangs 0.9 m along the arm direction, so the plate sits
    0.9 m to the chair's -local-Y side at the ceiling and the lamp ends over the chair."""
    from room_planner import proc_generated
    n = 0
    for ch in [o for o in bpy.data.objects if o.name.startswith("DentalChairFactory") and o.parent is None]:
        walls = [w for w in bpy.data.objects if w.type == "MESH" and w.name.endswith(".wall") and w.parent is None]
        zc = max((max((w.matrix_world @ Vector(c)).z for c in w.bound_box) for w in walls), default=2.7)
        side = ch.matrix_world.to_3x3() @ Vector((0, 1, 0)); side.z = 0; side.normalize()
        lamp = proc_generated.DentalCeilingLightFactory(1).spawn_asset(0)
        lamp.rotation_mode = "XYZ"; lamp.rotation_euler = (0, 0, ch.matrix_world.to_euler().z)         # the arm runs along the chair's +Y
        c = ch.matrix_world.translation
        lamp.location = (c.x - side.x * 0.9, c.y - side.y * 0.9, zc); n += 1
    return n


def ceiling_tint(rgb):
    """Only the ceiling finish: every `.ceiling` mesh gets one plain paint of this (linear) colour; fixtures and the T-bar grid stay. S10: pure-black ceiling -> dark warm brown."""
    mat = bpy.data.materials.get("ir_late_ceiling_tint") or bpy.data.materials.new("ir_late_ceiling_tint")
    mat.use_nodes = True; b = mat.node_tree.nodes["Principled BSDF"]; b.inputs["Base Color"].default_value = (*rgb, 1); b.inputs["Roughness"].default_value = 0.8; b["weathered"] = True
    n = 0
    for o in bpy.data.objects:
        if o.type == "MESH" and o.name.endswith(".ceiling") and o.parent is None:
            for sl in o.material_slots:
                sl.material = mat
            n += 1
    return n


def chandeliers(n=2):
    """Hang n crystal chandeliers (proc_assets.ChandelierFactory: emissive candle bulbs) over the café counter's length, each with a warm point light: S10's focal glow when the layout
    placed no coffee_bar zone (its own chandelier is placed only there). Skips rooms without a CafeCounterFactory."""
    from room_planner import proc_assets as pa
    cnt = next((o for o in bpy.data.objects if o.name.startswith("CafeCounterFactory") and o.parent is None), None)
    if cnt is None:
        return 0
    walls = [w for w in bpy.data.objects if w.type == "MESH" and w.name.endswith(".wall") and w.parent is None]
    zc = max((max((w.matrix_world @ Vector(c)).z for c in w.bound_box) for w in walls), default=2.8)
    mw = cnt.matrix_world; ax = mw.to_3x3() @ Vector((0, 1, 0)); ax.z = 0; ax.normalize(); half = cnt.dimensions[1] / 2
    done = 0
    for k in range(n):
        t = (k + 0.5) / n * 2 - 1                                      # -1..1 along the counter
        p = mw.translation + ax * (t * half * 0.7)
        ch = pa.ChandelierFactory(1000 + k).spawn_asset(900 + k); ch.location = (p.x, p.y, zc - 0.05)
        ld = bpy.data.lights.new(f"ir_late_chandelier_{k}", "POINT"); ld.energy = 260.0; ld.color = (1.0, 0.74, 0.45); ld.shadow_soft_size = 0.25
        lo = bpy.data.objects.new(f"PointLampFactory(chandelier).spawn_asset(late_{k})", ld); bpy.context.scene.collection.objects.link(lo); lo.location = (p.x, p.y, zc - 0.7)
        done += 1
    return done


def _panel_mat(rgb, slat=False):
    """Dark panelled walls: every room wall slot -> one wood-toned Principled with a raised-panel grid (a brick texture of 0.9 x 1.4 m cells on (distance along the wall, z), 6 cm grooves) driving
    colour and a bump, so the walls read as wainscot panelling (S10 ref: decorative dark panelled walls). Not weathered; the painted accent / tile faces of this module keep theirs."""
    mname = "ir_late_slat_wall" if slat else "ir_late_panel_wall"
    mat = bpy.data.materials.get(mname)
    if mat is None:
        mat = bpy.data.materials.new(mname); mat.use_nodes = True; N, L = mat.node_tree.nodes, mat.node_tree.links; b = N["Principled BSDF"]
        tc = N.new("ShaderNodeTexCoord"); sep = N.new("ShaderNodeSeparateXYZ"); L.new(tc.outputs["Object"], sep.inputs[0])
        s1 = N.new("ShaderNodeMath"); s1.operation = "ADD"; L.new(sep.outputs["X"], s1.inputs[0]); L.new(sep.outputs["Y"], s1.inputs[1])
        cb = N.new("ShaderNodeCombineXYZ"); L.new(s1.outputs["Value"], cb.inputs["X"]); L.new(sep.outputs["Z"], cb.inputs["Y"])
        br = N.new("ShaderNodeTexBrick"); br.offset = 0.0; br.squash = 1.0
        br.inputs["Scale"].default_value = 1.0; br.inputs["Brick Width"].default_value = 0.12 if slat else 0.9; br.inputs["Row Height"].default_value = 6.0 if slat else 1.4; br.inputs["Mortar Size"].default_value = 0.012 if slat else 0.06; br.inputs["Mortar Smooth"].default_value = 0.3
        if slat:
            br.offset = 0.0
        br.inputs["Color1"].default_value = (*rgb, 1); br.inputs["Color2"].default_value = (rgb[0] * (0.7 if slat else 0.85), rgb[1] * (0.7 if slat else 0.85), rgb[2] * (0.7 if slat else 0.85), 1); br.inputs["Mortar"].default_value = (rgb[0] * 0.25, rgb[1] * 0.25, rgb[2] * 0.25, 1)
        L.new(cb.outputs["Vector"], br.inputs["Vector"]); L.new(br.outputs["Color"], b.inputs["Base Color"])
        bp = N.new("ShaderNodeBump"); bp.inputs["Strength"].default_value = 1.0; bp.inputs["Distance"].default_value = 0.03; L.new(br.outputs["Fac"], bp.inputs["Height"]); L.new(bp.outputs["Normal"], b.inputs["Normal"])
        b.inputs["Roughness"].default_value = 0.42; b["weathered"] = True
    return mat


def panel_walls(rgb, slat=False):
    mat = _panel_mat(rgb, slat)
    n = 0
    for o in bpy.data.objects:
        if o.type == "MESH" and o.name.endswith(".wall") and o.parent is None:
            for sl in o.material_slots:
                if sl.material and not sl.material.name.startswith("ir_late_"):
                    sl.material = mat; n += 1
    return n


RUGS = None


def _rug_png(name, base, accent, trim):
    """data/venue_refs/rugs/src/<name>.png (generated) else a procedural oriental-style rug (field + medallion + banded border + noise), cached as data/venue_refs/rugs/<name>.png."""
    from pathlib import Path
    d = Path("/jarvis/project/robomituba/data/venue_refs/rugs")
    for src in (d / "src" / f"rug_{name}.png", d / "src" / f"{name}.png"):                # the generated files are rug_<name>.png (the first lookup used <name>.png and missed them)
        if src.exists():
            return src
    out = d / f"{name}.png"
    if out.exists():
        return out
    import random
    from PIL import Image, ImageDraw, ImageFilter
    W, H = 1024, 1536; im = Image.new("RGB", (W, H), base); dr = ImageDraw.Draw(im); r = random.Random(name)
    for k, (m, col) in enumerate(((0, trim), (40, base), (60, accent), (110, base), (130, trim), (150, base))):
        dr.rectangle((m, m, W - m, H - m), outline=col, width=18 if k in (2, 4) else 10)
    for y in range(190, H - 190, 70):                                          # border lozenges
        for x in (80, W - 80):
            dr.polygon([(x, y - 24), (x + 20, y), (x, y + 24), (x - 20, y)], fill=trim)
    for x in range(190, W - 190, 70):
        for y in (80, H - 80):
            dr.polygon([(x, y - 20), (x + 24, y), (x, y + 20), (x - 24, y)], fill=trim)
    cx, cy = W // 2, H // 2
    for s_, col in ((330, accent), (270, base), (220, trim), (150, accent), (90, base), (40, trim)):
        dr.polygon([(cx, cy - s_ * 1.5), (cx + s_, cy), (cx, cy + s_ * 1.5), (cx - s_, cy)], fill=col)
    for _ in range(260):                                                       # scattered motifs in the field
        x, y = r.randint(200, W - 200), r.randint(200, H - 200)
        if abs(x - cx) / 330 + abs(y - cy) / 495 > 1.1:
            dr.ellipse((x - 9, y - 9, x + 9, y + 9), fill=r.choice((accent, trim)))
    im = im.filter(ImageFilter.GaussianBlur(1.1)); px = im.load()
    for _ in range(60000):                                                     # wool noise
        x, y = r.randint(0, W - 1), r.randint(0, H - 1); c = px[x, y]; k = r.randint(-18, 18); px[x, y] = (max(0, min(255, c[0] + k)), max(0, min(255, c[1] + k)), max(0, min(255, c[2] + k)))
    d.mkdir(parents=True, exist_ok=True); im.save(out)
    return out


def _rug_mat(name, base, accent, trim):
    m = bpy.data.materials.get(f"ir_rug_{name}")
    if m is None:
        m = bpy.data.materials.new(f"ir_rug_{name}"); m.use_nodes = True; N, Lk = m.node_tree.nodes, m.node_tree.links; b = N["Principled BSDF"]
        t = N.new("ShaderNodeTexImage"); t.image = bpy.data.images.load(str(_rug_png(name, base, accent, trim)), check_existing=True); Lk.new(t.outputs["Color"], b.inputs["Base Color"])
        b.inputs["Roughness"].default_value = 0.92; b["weathered"] = True
    return m


def rugs():
    """Large woven rugs on the café floor (S10: 'the floor needs carpet'): one 2 x 3 m rug under each group of nearby tables (greedy clusters of tables within 1.9 m, an axis-aligned rug
    covering the group + 0.8 m margin, min 2 x 3 m, clipped to the floor) and one in front of the counter. Flat quads 6 mm above the floor (burgundy / navy alternate); skipped
    when they would run under the counter or off the floor."""
    floors = [o for o in bpy.data.objects if o.type == "MESH" and o.name.endswith(".floor") and o.parent is None]
    if not floors:
        return 0
    f0 = floors[0]; fp = [f0.matrix_world @ Vector(c) for c in f0.bound_box]; x0, x1, y0, y1 = min(p.x for p in fp), max(p.x for p in fp), min(p.y for p in fp), max(p.y for p in fp); fz = max(p.z for p in fp) + 0.006
    hosts = tuple(os.environ.get("ROOM_RUGS_HOSTS", "CafeTableFactory").split(","))                  # e.g. DisplayTableFactory for a boutique
    tabs = [o.matrix_world.translation.xy.copy() for o in bpy.data.objects if o.name.startswith(hosts) and o.parent is None]
    cnt = next((o for o in bpy.data.objects if o.name.startswith("CafeCounterFactory") and o.parent is None), None)
    cbox = None
    if cnt is not None:
        cb = [cnt.matrix_world @ Vector(c) for c in cnt.bound_box]; cbox = (min(p.x for p in cb) - 0.3, max(p.x for p in cb) + 0.3, min(p.y for p in cb) - 0.3, max(p.y for p in cb) + 0.3)
    pal = [("burgundy", (0.36, 0.07, 0.09), (0.12, 0.14, 0.3), (0.8, 0.7, 0.45)), ("navy", (0.08, 0.1, 0.24), (0.55, 0.22, 0.25), (0.85, 0.8, 0.65))]
    if os.environ.get("ROOM_RUGS_STYLE") == "jute":                                                       # a natural jute runner (S15 ref): low-contrast woven beige
        pal = [("jute", (0.62, 0.5, 0.34), (0.5, 0.4, 0.27), (0.72, 0.62, 0.45))]
    made = 0

    def quad(cx, cy, hx, hy, k):
        nonlocal made
        long_x = hx >= hy; nm, base, acc, trim = pal[k % 2]; m = _rug_mat(nm, tuple(int(c * 255) for c in base), tuple(int(c * 255) for c in acc), tuple(int(c * 255) for c in trim))
        bm = bmesh.new(); uv = bm.loops.layers.uv.verify()
        pts = [(cx - hx, cy - hy), (cx + hx, cy - hy), (cx + hx, cy + hy), (cx - hx, cy + hy)]
        uvs = [(0, 0), (0, 1), (1, 1), (1, 0)] if long_x else [(0, 0), (1, 0), (1, 1), (0, 1)]                   # the texture's long (v) axis along the rug's long side
        f = bm.faces.new([bm.verts.new((px, py, fz)) for px, py in pts])
        for lp, c in zip(f.loops, uvs):
            lp[uv].uv = c
        me = bpy.data.meshes.new("Rug"); bm.to_mesh(me); bm.free(); me.materials.append(m)
        o = bpy.data.objects.new(f"RugFactory({made}).spawn_asset({made})", me); bpy.context.scene.collection.objects.link(o); made += 1
    free = list(tabs); k = 0
    while free:
        seed = free.pop(0); grp = [seed] + [t for t in free if (t - seed).length < 1.9]
        free = [t for t in free if t not in grp]
        xs, ys = [t.x for t in grp], [t.y for t in grp]
        hx, hy = max((max(xs) - min(xs)) / 2 + 0.9, 1.0), max((max(ys) - min(ys)) / 2 + 0.9, 1.0)
        if max(hx, hy) < 1.5:
            hx, hy = (1.5, 1.0) if hx >= hy else (1.0, 1.5)
        cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
        cx = min(max(cx, x0 + hx + 0.3), x1 - hx - 0.3); cy = min(max(cy, y0 + hy + 0.3), y1 - hy - 0.3)
        if cbox is not None and cbox[0] < cx + hx and cx - hx < cbox[1] and cbox[2] < cy + hy and cy - hy < cbox[3]:
            continue
        quad(cx, cy, hx, hy, k); k += 1
    if cnt is not None:
        fv = cnt.matrix_world.to_3x3() @ Vector((1, 0, 0)); fv.z = 0; fv.normalize(); L_ = cnt.dimensions[1] * 0.7
        c0 = cnt.matrix_world.translation.xy + fv.xy * (cnt.dimensions[0] / 2 + 0.95)
        hx, hy = (0.7, L_ / 2) if abs(fv.x) > abs(fv.y) else (L_ / 2, 0.7)
        if x0 + hx < c0.x < x1 - hx and y0 + hy < c0.y < y1 - hy:
            quad(c0.x, c0.y, hx, hy, k)
    return made


def wall_band(rgb, z0, z1):
    """A horizontal colour band on every room wall between z0 and z1 (metres above the floor): the wall mesh is bisected at both heights (a wall of a few big quads must not lose a whole
    quad), then the faces inside get their own plain paint slot. S16 pharmacy: the green band behind the medicine wall."""
    mat = bpy.data.materials.get("ir_late_wall_band") or bpy.data.materials.new("ir_late_wall_band")
    mat.use_nodes = True; b = mat.node_tree.nodes["Principled BSDF"]; b.inputs["Base Color"].default_value = (*rgb, 1); b.inputs["Roughness"].default_value = 0.6; b["weathered"] = True
    if os.environ.get("ROOM_WALL_BAND_BRICK") == "1" and not any(n.type == "TEX_BRICK" for n in mat.node_tree.nodes):          # ROOM_WALL_BAND_BRICK=1: the band is running-bond brick in the band colour (S31: a grey-brick dado), in world metres
        nt = mat.node_tree; geo = nt.nodes.new("ShaderNodeNewGeometry"); br = nt.nodes.new("ShaderNodeTexBrick")
        br.inputs["Color1"].default_value = (*rgb, 1); br.inputs["Color2"].default_value = (min(1.0, rgb[0] * 1.35), min(1.0, rgb[1] * 1.35), min(1.0, rgb[2] * 1.35), 1)
        br.inputs["Mortar"].default_value = (rgb[0] * 0.45, rgb[1] * 0.45, rgb[2] * 0.45, 1); br.inputs["Scale"].default_value = 4.0; br.inputs["Mortar Size"].default_value = 0.012
        br.inputs["Brick Width"].default_value = 0.5; br.inputs["Row Height"].default_value = 0.25
        nt.links.new(geo.outputs["Position"], br.inputs["Vector"]); nt.links.new(br.outputs["Color"], b.inputs["Base Color"])
    n = 0
    for o in bpy.data.objects:
        if o.type != "MESH" or not o.name.endswith(".wall") or o.parent is not None:
            continue
        fz = min((o.matrix_world @ Vector(c)).z for c in o.bound_box); mw = o.matrix_world; inv = mw.inverted(); inv3 = inv.to_3x3()
        bm = bmesh.new(); bm.from_mesh(o.data)
        for z in (fz + z0, fz + z1):
            geom = list({*bm.faces, *(e for f in bm.faces for e in f.edges), *(v for f in bm.faces for v in f.verts)})
            bmesh.ops.bisect_plane(bm, geom=geom, dist=1e-4, plane_co=inv @ Vector((0, 0, z)), plane_no=(inv3 @ Vector((0, 0, 1))).normalized())
        if mat.name not in [m.name for m in o.data.materials if m]:
            o.data.materials.append(mat)
        idx = [m.name if m else "" for m in o.data.materials].index(mat.name)
        for f in bm.faces:
            c = mw @ f.calc_center_median()
            if fz + z0 < c.z < fz + z1 and abs((mw.to_3x3() @ f.normal).z) < 0.3:
                f.material_index = idx; n += 1
        bm.to_mesh(o.data); bm.free()
    return n


def spread_plants(min_d=2.0, prefixes=("OliveTreeFactory", "LargePlantContainerFactory", "SmallPlantFactory")):
    """Move floor plants that stand closer than min_d to an earlier one to a free spot along the room's walls, preferring corners: a boutique's four olive trees stood in one cluster round
    the fitting room and read as a hedge (S15). Candidates = a 0.5 m grid along each wall inset 0.45 m; a candidate is free when no other mesh with its base below 1.9 m (room parts, rugs,
    the plants themselves excluded) is within 0.35 m of it; score = distance to the nearest other plant (capped at 4 m) + 1.5 in a corner."""
    plants = [o for o in bpy.data.objects if o.type == "MESH" and o.parent is None and o.name.startswith(prefixes)]
    floors = [o for o in bpy.data.objects if o.type == "MESH" and o.name.endswith(".floor") and o.parent is None]
    if len(plants) < 2 or not floors:
        return 0
    fp = [floors[0].matrix_world @ Vector(c) for c in floors[0].bound_box]; x0, x1, y0, y1 = min(p.x for p in fp), max(p.x for p in fp), min(p.y for p in fp), max(p.y for p in fp)
    import re
    obst = []
    for o in bpy.data.objects:
        if o.type != "MESH" or o.parent is not None or o in plants or re.search(r"\.(wall|floor|ceiling|exterior)\b", o.name) or o.name.startswith(("Rug", "BigGlass", "Rotunda")):
            continue
        bb = [o.matrix_world @ Vector(c) for c in o.bound_box]
        if min(p.z for p in bb) < 1.9 and max(p.z for p in bb) > 0.2:
            obst.append((min(p.x for p in bb), max(p.x for p in bb), min(p.y for p in bb), max(p.y for p in bb)))
    m = 0.45; cands = []
    for k in range(int((x1 - x0) / 0.5) + 1):
        cands += [(x0 + m + k * 0.5, y0 + m), (x0 + m + k * 0.5, y1 - m)]
    for k in range(int((y1 - y0) / 0.5) + 1):
        cands += [(x0 + m, y0 + m + k * 0.5), (x1 - m, y0 + m + k * 0.5)]
    cands = [c for c in cands if x0 + m - 1e-6 <= c[0] <= x1 - m + 1e-6 and y0 + m - 1e-6 <= c[1] <= y1 - m + 1e-6]
    free = lambda c: not any(b[0] - 0.35 < c[0] < b[1] + 0.35 and b[2] - 0.35 < c[1] < b[3] + 0.35 for b in obst)
    kept = []; moved = 0
    for o in plants:
        p = o.matrix_world.translation
        if all(math.hypot(p.x - q[0], p.y - q[1]) >= min_d for q in kept):
            kept.append((p.x, p.y)); continue
        best, bs = None, -1.0
        for c in cands:
            if not free(c):
                continue
            d = min((math.hypot(c[0] - q[0], c[1] - q[1]) for q in kept), default=4.0)
            if d < min_d:
                continue
            corner = (abs(c[0] - x0 - m) < 0.3 or abs(c[0] - x1 + m) < 0.3) and (abs(c[1] - y0 - m) < 0.3 or abs(c[1] - y1 + m) < 0.3)
            s = min(d, 4.0) + (1.5 if corner else 0.0)
            if s > bs:
                best, bs = c, s
        if best is None:
            kept.append((p.x, p.y)); continue
        o.location.x += best[0] - p.x; o.location.y += best[1] - p.y; kept.append(best); moved += 1
        bpy.context.view_layer.update()
    return moved


def market_ceiling(venue="grocery"):
    """A low dark-red timber ceiling like the market refs: main beams every 1.8 m across the short axis (0.14 x 0.3 m), rafters every 0.45 m the other way (0.05 x 0.12), a round steel duct
    along the long axis, fluorescent tubes (1.2 m emissive + a soft area light) on short rods every 3 m and a track of spot heads. Replaces the room's ceiling lights and the plaster
    `.ceiling` face by a dark underside. Only in the largest room whose venue is `venue` (plans room_venues) or, without that map, the largest room."""
    import json
    rooms = {}
    for o in bpy.data.objects:
        if o.type == "MESH" and o.name.endswith(".ceiling") and o.parent is None:
            bb = [o.matrix_world @ Vector(c) for c in o.bound_box]
            rooms[o.name] = (o, min(p.x for p in bb), max(p.x for p in bb), min(p.y for p in bb), max(p.y for p in bb), max(p.z for p in bb))
    if not rooms:
        return 0
    name = max(rooms, key=lambda k: (rooms[k][2] - rooms[k][1]) * (rooms[k][4] - rooms[k][3])); o, x0, x1, y0, y1, zc = rooms[name]
    mat = lambda n, rgb, r, m=0.0: _mat_simple(n, rgb, r, m)
    beam_m = mat("ir_mk_beam", (0.22, 0.06, 0.05), 0.7); raft_m = mat("ir_mk_rafter", (0.1, 0.07, 0.05), 0.8); deck_m = mat("ir_mk_deck", (0.08, 0.06, 0.045), 0.9); duct_m = mat("ir_mk_duct", (0.6, 0.62, 0.64), 0.35, 0.9)
    for sl in o.material_slots:
        sl.material = deck_m
    for l in [l for l in bpy.data.objects if l.type == "LIGHT" and l.location.z > zc - 0.6 and x0 <= l.location.x <= x1 and y0 <= l.location.y <= y1]:
        bpy.data.objects.remove(l, do_unlink=True)
    long_x = (x1 - x0) >= (y1 - y0)
    boxes = []                                                              # (material, cx, cy, cz, sx, sy, sz)
    n_b = max(2, int(((y1 - y0) if long_x else (x1 - x0)) / 1.8))
    for k in range(int(((x1 - x0) if long_x else (y1 - y0)) / 1.8)):
        c = (x0 if long_x else y0) + 0.9 + k * 1.8
        boxes.append((beam_m, c if long_x else (x0 + x1) / 2, (y0 + y1) / 2 if long_x else c, zc - 0.16, 0.14 if long_x else (x1 - x0), (y1 - y0) if long_x else 0.14, 0.3))
    for k in range(int(((x1 - x0) if long_x else (y1 - y0)) / 0.45)):
        c = (x0 if long_x else y0) + 0.225 + k * 0.45
        boxes.append((raft_m, c if long_x else (x0 + x1) / 2, (y0 + y1) / 2 if long_x else c, zc - 0.07, 0.05 if long_x else (x1 - x0), (y1 - y0) if long_x else 0.05, 0.12))
    for mt in (beam_m, raft_m):
        bm = bmesh.new()
        for m_, cx, cy, cz, sx, sy, sz in boxes:
            if m_ is not mt:
                continue
            r = bmesh.ops.create_cube(bm, size=1.0); bmesh.ops.scale(bm, vec=(sx, sy, sz), verts=r["verts"]); bmesh.ops.translate(bm, vec=(cx, cy, cz), verts=r["verts"])
        me = bpy.data.meshes.new("MarketBeams"); bm.to_mesh(me); bm.free(); me.materials.append(mt)
        ob = bpy.data.objects.new(f"CeilingBeamsFactory(market).spawn_asset({mt.name})", me); bpy.context.scene.collection.objects.link(ob)
    # round duct along the long axis, off-centre
    L_ = (x1 - x0) if long_x else (y1 - y0)
    bm = bmesh.new(); bmesh.ops.create_cone(bm, cap_ends=True, segments=20, radius1=0.26, radius2=0.26, depth=L_ - 0.4)
    if long_x:
        bmesh.ops.rotate(bm, cent=(0, 0, 0), matrix=__import__("mathutils").Matrix.Rotation(math.pi / 2, 3, "Y"), verts=bm.verts); loc = ((x0 + x1) / 2, y0 + (y1 - y0) * 0.3, zc - 0.5)
    else:
        bmesh.ops.rotate(bm, cent=(0, 0, 0), matrix=__import__("mathutils").Matrix.Rotation(math.pi / 2, 3, "X"), verts=bm.verts); loc = (x0 + (x1 - x0) * 0.3, (y0 + y1) / 2, zc - 0.5)
    me = bpy.data.meshes.new("MarketDuct"); bm.to_mesh(me); bm.free(); me.materials.append(duct_m)
    dob = bpy.data.objects.new("CeilingDuctFactory(market).spawn_asset(0)", me); bpy.context.scene.collection.objects.link(dob); dob.location = loc
    # fluorescent tubes (emissive 1.2 m) on rods + a soft area light each; spot heads on a track
    glow = bpy.data.materials.get("ir_mk_tube") or bpy.data.materials.new("ir_mk_tube"); glow.use_nodes = True; gb = glow.node_tree.nodes["Principled BSDF"]
    gb.inputs["Base Color"].default_value = (1, 1, 1, 1); gb.inputs["Emission Color"].default_value = (1.0, 0.97, 0.9, 1); gb.inputs["Emission Strength"].default_value = 9.0; gb["weathered"] = True
    nt = 0
    step = 3.0
    pos = []
    for i in range(max(1, int(L_ / step))):
        t = (x0 if long_x else y0) + step / 2 + i * step
        for f_ in (0.2, 0.55, 0.85):
            pos.append((t, (y0 + (y1 - y0) * f_) if long_x else None, f_))
    for t, other, f_ in pos:
        cx, cy = (t, other) if long_x else (x0 + (x1 - x0) * f_, t)
        bm = bmesh.new(); r = bmesh.ops.create_cube(bm, size=1.0); bmesh.ops.scale(bm, vec=(1.2, 0.1, 0.05) if long_x else (0.1, 1.2, 0.05), verts=r["verts"])
        me = bpy.data.meshes.new("Tube"); bm.to_mesh(me); bm.free(); me.materials.append(glow)
        tb = bpy.data.objects.new(f"LinearLedFactory(market_{nt}).spawn_asset(0)", me); bpy.context.scene.collection.objects.link(tb); tb.location = (cx, cy, zc - 0.62)
        ld = bpy.data.lights.new(f"ir_mk_tube_{nt}", "AREA"); ld.shape = "RECTANGLE"; ld.size = 1.2; ld.size_y = 0.12; ld.energy = 60.0; ld.color = (1.0, 0.95, 0.85)
        lo = bpy.data.objects.new(f"PointLampFactory(market).spawn_asset(tube_{nt})", ld); bpy.context.scene.collection.objects.link(lo); lo.location = (cx, cy, zc - 0.66); lo.rotation_euler = (math.pi, 0, 0); nt += 1
    spots = 0
    rail_m = mat("ir_mk_track", (0.04, 0.04, 0.045), 0.5, 0.8)
    for f_ in (0.4, 0.7):
        for i in range(int(L_ / 1.2)):
            t = (x0 if long_x else y0) + 0.6 + i * 1.2; cx, cy = (t, y0 + (y1 - y0) * f_) if long_x else (x0 + (x1 - x0) * f_, t)
            bm = bmesh.new(); bmesh.ops.create_cone(bm, segments=10, radius1=0.05, radius2=0.075, depth=0.13); me = bpy.data.meshes.new("Spot"); bm.to_mesh(me); bm.free(); me.materials.append(rail_m)
            sp = bpy.data.objects.new(f"TrackSpotFactory(market_{spots}).spawn_asset(0)", me); bpy.context.scene.collection.objects.link(sp); sp.location = (cx, cy, zc - 0.5)
            ld = bpy.data.lights.new(f"ir_mk_spot_{spots}", "SPOT"); ld.energy = 25.0; ld.spot_size = math.radians(40); ld.spot_blend = 0.4; ld.shadow_soft_size = 0.05; ld.color = (1.0, 0.9, 0.75)
            lo = bpy.data.objects.new(f"PointLampFactory(market).spawn_asset(spot_{spots})", ld); bpy.context.scene.collection.objects.link(lo); lo.location = (cx, cy, zc - 0.56); spots += 1
    return nt + spots


def _mat_simple(name, rgb, rough, metallic=0.0):
    m = bpy.data.materials.get(name)
    if m is None:
        m = bpy.data.materials.new(name); m.use_nodes = True; b = m.node_tree.nodes["Principled BSDF"]
        b.inputs["Base Color"].default_value = (*rgb, 1); b.inputs["Roughness"].default_value = rough; b.inputs["Metallic"].default_value = metallic; b["weathered"] = True
    return m


def _fixture_boxes():
    fx = []
    for o in bpy.data.objects:
        if o.type == "MESH" and o.parent is None and o.name.split("(")[0].startswith(("ShowerEnclosure", "Bathtub", "Tub", "Toilet", "Vanity", "OakBasinVanity", "LongOakVanity", "WashBasin", "HomeVanity")):
            q = [o.matrix_world @ Vector(c) for c in o.bound_box]
            fx.append((min(v.x for v in q), max(v.x for v in q), min(v.y for v in q), max(v.y for v in q)))
    return fx


def _leaf_box(o):
    q = [o.matrix_world @ v.co for v in o.data.vertices]
    return (min(v.x for v in q), max(v.x for v in q), min(v.y for v in q), max(v.y for v in q))


def _hits(box, fx, m=0.03):
    return any(box[0] - m < f[1] and box[1] + m > f[0] and box[2] - m < f[3] and box[3] + m > f[2] for f in fx)


def _swing_safe(o, c, nrm, rzc, sgn, fx, out):
    """ROOM_DOOR_SWING_SAFE=1 (H3 r21, three rounds of 'the leaf cuts across the shower tray'): the swept area of the open leaf (the union of its closed and its 90 deg boxes) must clear every shower / tub / WC / vanity
    box. If it does not: try the opposite swing; if that hits too, the leaf becomes a POCKET door (closed pose, slid along the wall by its own width into the wall, like the ramen door)."""
    def swept(rz):
        o.rotation_euler[2] = rzc; bpy.context.view_layer.update(); a = _leaf_box(o)
        o.rotation_euler[2] = rz; bpy.context.view_layer.update(); b = _leaf_box(o)
        return (min(a[0], b[0]), max(a[1], b[1]), min(a[2], b[2]), max(a[3], b[3]))
    cur = o.rotation_euler[2]
    if not fx or not _hits(swept(cur), fx):
        o.rotation_euler[2] = cur; return
    alt = rzc - (cur - rzc)                                                      # the other way round
    if not _hits(swept(alt), fx):
        out["swing_flipped"] = out.get("swing_flipped", 0) + 1; return          # rotation already set by swept()
    o.rotation_euler[2] = rzc; bpy.context.view_layer.update()
    tw = Vector((-nrm.y, nrm.x, 0.0)); piv = o.matrix_world.translation; sd = 1.0 if (c - piv).dot(tw) >= 0 else -1.0
    wdt = max(_leaf_box(o)[1] - _leaf_box(o)[0], _leaf_box(o)[3] - _leaf_box(o)[2])
    sh = tw * sd * (wdt * 0.98)
    if o.parent is not None:
        o.location = o.location + ((o.parent.matrix_world @ o.matrix_parent_inverse).to_3x3().inverted() @ sh)
    else:
        o.location = o.location + sh
    bpy.context.view_layer.update(); out["pocket_doors"] = out.get("pocket_doors", 0) + 1


def open_doors():
    """User 2026-10-18: doors between rooms and cubicle doors must stand open so a person can pass. (1) every flush leaf (architecture_pass.flush_doors) is
    swung to 90 deg from its closed pose when it is closed or ajar (< 75 deg; service-room doors were shut on purpose), into the room unless the leaf would
    then stand in a corridor; (2) ToiletStallFactory meshes are rebuilt with the open door. ROOM_OPEN_DOORS=0 turns it off."""
    out = {"leaves_opened": 0, "stalls": 0}
    halls = []
    for o in bpy.data.objects:
        if o.type == "MESH" and o.name.startswith("hallway") and o.name.endswith(".floor"):
            pts = [o.matrix_world @ Vector(c) for c in o.bound_box]
            halls.append((min(q.x for q in pts), max(q.x for q in pts), min(q.y for q in pts), max(q.y for q in pts)))
    fbs = []                                                    # every room / hallway floor box: a door opens only where BOTH sides have a floor (user 2026-10-21: 'open a door that joins rooms, shut one that leads nowhere')
    for o in bpy.data.objects:
        if o.type == "MESH" and o.name.endswith(".floor"):
            pts = [o.matrix_world @ Vector(c) for c in o.bound_box]
            fbs.append((min(q.x for q in pts), max(q.x for q in pts), min(q.y for q in pts), max(q.y for q in pts)))
    out["kept_shut"] = 0
    fx_ = _fixture_boxes() if os.environ.get("ROOM_DOOR_SWING_SAFE") == "1" else []
    for o in list(bpy.data.objects):
        if o.type != "MESH" or o.parent is None or not o.data.name.startswith("ir_flush_leaf"):
            continue
        c = o.parent.matrix_world.translation.copy()
        nrm = o.parent.matrix_world.to_3x3() @ Vector((0, 1, 0)); nrm.z = 0
        if nrm.length < 1e-6:
            continue
        nrm.normalize()
        if fbs and (os.environ.get("ROOM_OPEN_DOORS_ANY") != "1" or os.environ.get("ROOM_SHUT_EXTERIOR_PLUG") == "1"):    # ROOM_OPEN_DOORS_ANY=1: the old behaviour (open every leaf)
            sides = [any(b[0] - 0.05 <= (c + nrm * k).x <= b[1] + 0.05 and b[2] - 0.05 <= (c + nrm * k).y <= b[3] + 0.05 for b in fbs) for k in (0.6, -0.6)]
            if not all(sides):
                out["kept_shut"] += 1; out.setdefault("kept_shut_at", []).append((o.parent.name, round(c.x, 2), round(c.y, 2), [int(x) for x in sides]))     # which doors stayed closed, and which side has no floor
                if os.environ.get("ROOM_SHUT_DOOR_WALL") == "1":              # O2 r20 / N2: a door in the building's outer wall leads nowhere (the glass leaf shows the exterior shell, tan) -> the leaf takes the room's wall material (a painted-shut door in its casing)
                    ks_ = [k_ for k_, ok_ in zip((0.6, -0.6), sides) if ok_]
                    wm_ = None
                    if ks_:
                        q_ = c + nrm * ks_[0]
                        for fo_ in bpy.data.objects:
                            if fo_.type == "MESH" and fo_.name.endswith(".floor"):
                                pf_ = [fo_.matrix_world @ Vector(cc_) for cc_ in fo_.bound_box]
                                if min(v_.x for v_ in pf_) - 0.05 <= q_.x <= max(v_.x for v_ in pf_) + 0.05 and min(v_.y for v_ in pf_) - 0.05 <= q_.y <= max(v_.y for v_ in pf_) + 0.05:
                                    wo_ = bpy.data.objects.get(fo_.name[:-len(".floor")] + ".wall")
                                    wm_ = None
                                    if wo_ is not None:                                        # the material of the wall face NEAREST the door, on the room side (slot 0 can be a feature wood panel: O2 r24 'a tan leaf in the doorway')
                                        inv_ = wo_.matrix_world.inverted(); cl_ = inv_ @ q_; best_ = None
                                        for pg_ in wo_.data.polygons:
                                            if abs(pg_.normal.z) > 0.3 or pg_.area < 0.05:
                                                continue
                                            dd_ = (pg_.center - cl_).length
                                            if best_ is None or dd_ < best_[0]:
                                                best_ = (dd_, pg_.material_index)
                                        if best_ is not None and best_[1] < len(wo_.material_slots):
                                            wm_ = wo_.material_slots[best_[1]].material
                                        wm_ = wm_ or next((sl_.material for sl_ in wo_.material_slots if sl_.material), None)
                                    break
                    if wm_ is not None:
                        o.data = o.data.copy(); o.data.materials.clear(); o.data.materials.append(wm_)
                        cs_ = next((ch_ for ch_ in o.parent.children if ch_.name.startswith("DoorCasingFactory")), None)
                        if cs_ is not None:                                  # O2 r21: walled up COMPLETELY: a wall-material plug fills the casing's opening, the casing and the leaf are hidden
                            import bmesh as _bm
                            me_ = bpy.data.meshes.new("DoorPlug"); b_ = _bm.new(); _bm.ops.create_cube(b_, size=1.0); b_.to_mesh(me_); b_.free(); me_.materials.append(wm_)
                            pl_ = bpy.data.objects.new(f"DoorPlug({o.parent.name})", me_); bpy.context.scene.collection.objects.link(pl_)
                            cc_ = sum((Vector(q_) for q_ in cs_.bound_box), Vector()) / 8; d_ = cs_.dimensions
                            from mathutils import Matrix as _M
                            pl_.parent = o.parent; pl_.matrix_parent_inverse = _M.Identity(4)
                            pl_["ir_plug_wall"] = wo_.name
                            pl_.matrix_local = cs_.matrix_local @ _M.Translation(cc_) @ _M.Diagonal(Vector((max(d_.x / max(cs_.scale.x, 1e-6) - 0.16, 0.3), max(d_.y / max(cs_.scale.y, 1e-6) - 0.02, 0.1), max(d_.z / max(cs_.scale.z, 1e-6) - 0.02, 0.5), 1.0)))
                            cs_.hide_render = True; cs_.hide_viewport = True; o.hide_render = True; o.hide_viewport = True
                        out["shut_walled"] = out.get("shut_walled", 0) + 1
                        continue
                if os.environ.get("ROOM_SHUT_DOOR_GLASS") == "1":          # O5 r8 LAY-01: a closed timber leaf filling a meeting-room doorway that leads outside -> a clear glass leaf, like the room's glass partitions
                    gm = bpy.data.materials.get("ir_shut_door_glass")
                    if gm is None:
                        gm = bpy.data.materials.new("ir_shut_door_glass"); gm.use_nodes = True; N_, L_ = gm.node_tree.nodes, gm.node_tree.links
                        tr_ = N_.new("ShaderNodeBsdfTransparent"); tr_.inputs["Color"].default_value = (0.9, 0.96, 1.0, 1); gl_ = N_.new("ShaderNodeBsdfGlossy"); gl_.inputs["Roughness"].default_value = 0.03
                        mx_ = N_.new("ShaderNodeMixShader"); mx_.inputs["Fac"].default_value = 0.06; L_.new(tr_.outputs[0], mx_.inputs[1]); L_.new(gl_.outputs[0], mx_.inputs[2])
                        out_ = next(n_ for n_ in N_ if n_.type == "OUTPUT_MATERIAL"); L_.new(mx_.outputs[0], out_.inputs["Surface"])
                    o.data = o.data.copy(); o.data.materials.clear(); o.data.materials.append(gm); out["shut_glazed"] = out.get("shut_glazed", 0) + 1
                continue
        fs = [pg.center.copy() for pg in o.data.polygons]
        o.rotation_mode = "XYZ"; rz0 = o.rotation_euler[2]

        def cost(rz):                                               # closed pose = the z rotation that lays the leaf thinnest across the wall normal
            o.rotation_euler[2] = rz; bpy.context.view_layer.update()
            xs = [(o.matrix_world @ q - c).dot(nrm) for q in fs]
            m = sum(xs) / len(xs)
            return (sum((x - m) ** 2 for x in xs) / len(xs)) ** 0.5
        rzc = min((math.radians(d) for d in range(-180, 180, 2)), key=cost)
        d = (rz0 - rzc + math.pi / 2) % math.pi - math.pi / 2         # the closed pose repeats every 180 deg (a leaf is as thin across the wall either way round): fold into [-90, 90), so a leaf shut the
        # 'other way round' reads closed, not 'already open' (P2: 2 of 16 leaves stayed shut -- door.003 / door.009 sat at exactly 180 deg from the cost minimum)
        if abs(d) >= math.radians(75):
            o.rotation_euler[2] = rz0; continue
        rzc = rz0 - d                                                    # the closed pose this leaf is actually near
        o.rotation_euler[2] = rzc + math.copysign(math.radians(90), d if abs(d) > 1e-3 else 1.0); bpy.context.view_layer.update()
        tw_ = Vector((-nrm.y, nrm.x, 0.0)); hs_ = 1.0 if (o.matrix_world.translation - c).dot(tw_) > 0 else -1.0
        sh_ = Vector(tw_) * (-hs_ * float(os.environ.get("ROOM_OPEN_DOOR_SHIFT") or 0.035))        # the pivot sits on the opening's edge, so the swung leaf (4.5 cm thick) stood half inside the casing's jamb ('the door goes through its frame', M r15): slide it that far into the opening
        if o.parent is not None:                                  # a translation in the parent's frame: assigning matrix_world re-derived rotation_euler (an equivalent but different Euler), and the corridor flip below sets only its z
            o.location = o.location + ((o.parent.matrix_world @ o.matrix_parent_inverse).to_3x3().inverted() @ sh_)
        else:
            o.location = o.location + sh_
        bpy.context.view_layer.update()
        m_ = o.matrix_world @ (sum((v.co for v in o.data.vertices), Vector()) / max(1, len(o.data.vertices)))
        if any(b[0] < m_.x < b[1] and b[2] < m_.y < b[3] for b in halls):      # standing in the corridor: swing the other way (into the room)
            o.rotation_euler[2] = rzc - math.copysign(math.radians(90), d if abs(d) > 1e-3 else 1.0)
        if os.environ.get("ROOM_DOOR_SWING_SAFE") == "1":
            _swing_safe(o, c, nrm, rzc, 1.0 if abs(d) <= 1e-3 or d > 0 else -1.0, fx_, out)
        out["leaves_opened"] += 1
    bpy.context.view_layer.update()
    from room_planner import proc_assets as pa
    for o in list(bpy.data.objects):
        if o.type == "MESH" and o.name.startswith("ToiletStallFactory") and o.data.materials:
            new = pa.ToiletStallFactory(0).spawn_asset(0)
            mats = list(o.data.materials)
            for k, m in enumerate(mats[:1]):                          # keep this stall's own laminate colour
                new.data.materials[k] = m
            o.data = new.data
            bpy.data.objects.remove(new, do_unlink=True); out["stalls"] += 1
    return out


def sync_plugs():
    """O2-DOOR-3: a DoorPlug takes the wall material it saw when open_doors ran; later kit passes (wall texture / tile / paint) replace the wall's materials, leaving the plug in the old tan
    one. Re-read the wall material nearest to every plug (call last in the kit stage; idempotent)."""
    n = 0
    for pl in [o for o in bpy.data.objects if o.type == "MESH" and o.get("ir_plug_wall")]:
        wo = bpy.data.objects.get(pl["ir_plug_wall"])
        if wo is None or not wo.material_slots:
            continue
        cl = wo.matrix_world.inverted() @ pl.matrix_world.translation; best = None
        for pg in wo.data.polygons:
            if abs(pg.normal.z) > 0.3 or pg.area < 0.05:
                continue
            dd = (pg.center - cl).length
            if best is None or dd < best[0]:
                best = (dd, pg.material_index)
        mt = wo.material_slots[best[1]].material if best and best[1] < len(wo.material_slots) else None
        if mt is not None:
            pl.data = pl.data.copy(); pl.data.materials.clear(); pl.data.materials.append(mt); n += 1
    return n


def open_blinds():
    """ROOM_OPEN_BLINDS=1: remove the roller / venetian blinds that architecture_pass draws over office windows. With them down every window reads as a grey panel (floor C r21:
    '창문 어디감?') and the outside card behind it is never seen."""
    n = 0
    for o in list(bpy.data.objects):
        if o.name.startswith("RollerBlindFactory") or o.name.startswith("VenetianBlindFactory"):
            bpy.data.objects.remove(o, do_unlink=True); n += 1
    return n


def recolor_openings():
    """DOOR_FRAME_RGB / DOOR_LEAF_RGB = "r,g,b": colour the door casings + window frames (one material, ir_office_door_frame) and the door leaves (ir_office_door_leaf).
    On a floor with flat grey walls the neutral grey casing and leaf made every door and window read as 'missing' (floor C r18/r19, user 10-19: '문 어디감?')."""
    n = 0
    for name, key in (("ir_office_door_frame", "DOOR_FRAME_RGB"), ("ir_office_door_leaf", "DOOR_LEAF_RGB")):
        v = os.environ.get(key)
        m = bpy.data.materials.get(name)
        if not v or m is None or not m.use_nodes:
            continue
        rgb = [float(x) for x in v.split(",")]
        for nd in m.node_tree.nodes:
            if nd.bl_idname == "ShaderNodeBsdfPrincipled":
                for lk in list(nd.inputs["Base Color"].links):               # a weathered material carries its OLD colour inside the dirt chain: cut it so the new colour shows
                    m.node_tree.links.remove(lk)
                nd.inputs["Base Color"].default_value = (*rgb, 1.0); n += 1
    return n


def apply(plans):
    out = {}
    if os.environ.get("DOOR_FRAME_RGB") or os.environ.get("DOOR_LEAF_RGB"):
        out["openings_recoloured"] = recolor_openings()
    if os.environ.get("ROOM_OPEN_BLINDS") == "1":
        out["blinds_removed"] = open_blinds()
    if os.environ.get("ROOM_BIGGLASS") or os.environ.get("ROOM_TERRACE_GLAZE"):
        from room_planner import big_glass
        out["bigglass_swept"] = big_glass.sweep()
    rgb = (plans.get("style_spec") or {}).get("feature_rgb")
    if os.environ.get("ROOM_FEATURE_WALL") == "1" and rgb:
        out["feature_wall_faces"] = paint_behind("ExamTableFactory", _paint_mat(rgb))
    if os.environ.get("ROOM_TILE_WALL"):                                    # e.g. CafeCounterFactory: white square tile on the wall behind the counter
        out["tile_wall_faces"] = paint_behind(os.environ["ROOM_TILE_WALL"], _tile_mat())
    st = plans.get("style_spec") or {}
    if os.environ.get("ROOM_SMOOTH_FLOOR") == "1" and st.get("floor_rgb"):
        out["smooth_floor"] = smooth_floor([min(1.0, c * 1.1) for c in st["floor_rgb"]])
    wr_ = st.get("wall_rgb") or ([(c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4) for c in st["wall_srgb"]] if st.get("wall_srgb") else None)      # a kit with only wall_srgb (hotel: wall_rgb null) skipped the flat paint (H2 r20)
    if os.environ.get("ROOM_FLAT_WALLS") == "1" and wr_:
        out["flat_walls"] = flat_walls([min(1.0, c + (1.0 - c) * 0.35) for c in wr_])
    if os.environ.get("ROOM_CEILING_RGB"):                                  # "r,g,b" linear, e.g. 0.09,0.06,0.045 (dark warm brown)
        out["ceiling_tint"] = ceiling_tint([float(x) for x in os.environ["ROOM_CEILING_RGB"].split(",")])
    if os.environ.get("ROOM_PANEL_WALLS"):                                  # "r,g,b" linear wood tone, e.g. 0.07,0.04,0.025
        pv_ = os.environ["ROOM_PANEL_WALLS"].split(",")                      # optional 4th field "slat": vertical oak slats (12 cm) instead of raised panels
        out["panel_walls"] = panel_walls([float(x) for x in pv_[:3]], slat=len(pv_) > 3 and pv_[3].strip() == "slat")
    if os.environ.get("ROOM_WALL_BAND"):                                    # "r,g,b,z0,z1": linear colour and the band's heights above the floor, e.g. 0.18,0.4,0.05,2.0,2.5
        v_ = [float(x) for x in os.environ["ROOM_WALL_BAND"].split(",")]
        out["wall_band"] = wall_band(v_[:3], v_[3], v_[4])
    if os.environ.get("ROOM_MARKET_CEILING") == "1":                       # dark-red timber beams + duct + tubes + spots in the largest room (the grocery market hall)
        out["market_ceiling"] = market_ceiling()
    if os.environ.get("ROOM_SPREAD_PLANTS"):                               # min distance in metres, e.g. 2.0
        out["plants_moved"] = spread_plants(float(os.environ["ROOM_SPREAD_PLANTS"]))
    if os.environ.get("ROOM_SLAT_BEHIND"):                                  # "Prefix[:r,g,b]": warm oak slats on the wall behind the first object with that name prefix (e.g. CafeBanquetteFactory)
        pv_ = os.environ["ROOM_SLAT_BEHIND"].split(":"); rgb_ = [float(x) for x in pv_[1].split(",")] if len(pv_) > 1 else [0.3, 0.16, 0.07]
        out["slat_behind_faces"] = paint_behind(pv_[0], _panel_mat(rgb_, True))
    if os.environ.get("ROOM_RUGS") == "1":
        out["rugs"] = rugs()
    if os.environ.get("ROOM_CHANDELIER"):                                   # number of chandeliers over the café counter, e.g. 2
        out["chandeliers"] = chandeliers(int(os.environ["ROOM_CHANDELIER"]))
    if os.environ.get("ROOM_DENTAL_LIGHT") == "1":
        out["dental_lights"] = dental_light()
    if os.environ.get("ROOM_WHITE_CEILING") in ("1", "grid", "slim"):
        out["white_ceiling"] = white_ceiling()
    return out
