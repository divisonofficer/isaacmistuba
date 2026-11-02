"""Ceiling of the warm clinic reception lobby (VLM refs S17 / D3). Hooked from kit_lighting before architecture_textures, only when ROOM_CLINIC_LOBBY=1.

    from clinic_lobby_ceiling import apply; stats["clinic_lobby_ceiling"] = apply(plans)

For every room whose venue is 'clinic-reception' (plans['room_venues'][room], or plans['style_spec']['venue'] for a single room):
  * removes the office ceiling kit inside the room: CeilingGrid, LinearLed, Diffuser, AcCassette objects, the grid's ir_led_* AREA lights and any lamp / ceiling
    fixture mesh or light above 2 m (the 'acoustic tiles + fluorescent tubes' look), keeping the room's own plaster `.ceiling`
  * builds a rounded-rectangle COVE: a lowered white centre panel (7 cm drop), a warm glowing ring (2800 K emissive) in the gap around it, 4 soft AREA lights
  * hangs 3 round pendants (cream shade, warm glowing underside) over the oak louver desk, found as the object named OakLouverDeskFactory in the room
Everything is plain geometry + a few lights; nothing is removed outside the lobby room.
"""
from __future__ import annotations

import math
import os

import bpy
from mathutils import Vector

WARM = (1.0, 0.72, 0.42)
REMOVE_BASES = ("CeilingGridFactory", "LinearLedFactory", "DiffuserFactory", "AcCassetteFactory", "SprinklerFactory")


def _mat(name, rgb, rough=0.6, emit=0.0):
    m = bpy.data.materials.get(name)
    if m is not None:
        return m
    m = bpy.data.materials.new(name); m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*rgb, 1); b.inputs["Roughness"].default_value = rough
    if emit:
        b.inputs["Emission Color"].default_value = (*rgb, 1); b.inputs["Emission Strength"].default_value = emit
    return m


def _rrect(cx, cy, w, h, r, n=8):
    """Closed rounded-rectangle outline (list of (x, y)), corner radius r, n points per corner."""
    r = min(r, w / 2, h / 2); pts = []
    for sx, sy, a0 in ((1, 1, 0.0), (-1, 1, 90.0), (-1, -1, 180.0), (1, -1, 270.0)):
        ccx, ccy = cx + sx * (w / 2 - r), cy + sy * (h / 2 - r)
        for k in range(n + 1):
            a = math.radians(a0 + 90.0 * k / n); pts.append((ccx + r * math.cos(a), ccy + r * math.sin(a)))
    return pts


def _band(name, outer, inner, z, mat):
    """A flat band mesh between two outlines of equal point count (faces facing down)."""
    import bmesh
    bm = bmesh.new(); vo = [bm.verts.new((x, y, z)) for x, y in outer]; vi = [bm.verts.new((x, y, z)) for x, y in inner]; n = len(vo)
    for k in range(n):
        bm.faces.new((vo[k], vi[k], vi[(k + 1) % n], vo[(k + 1) % n]))
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free(); me.materials.append(mat)
    o = bpy.data.objects.new(name, me); bpy.context.scene.collection.objects.link(o)
    return o


def _panel(name, outline, z, mat):
    import bmesh
    bm = bmesh.new(); vs = [bm.verts.new((x, y, z)) for x, y in outline]; bm.faces.new(reversed(vs))
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free(); me.materials.append(mat)
    o = bpy.data.objects.new(name, me); bpy.context.scene.collection.objects.link(o)
    return o


def _rooms(plans):
    import room_dressing as rd
    rv = plans.get("room_venues") or {}; sv = (plans.get("style_spec") or {}).get("venue")
    for name, parts in rd._rooms().items():
        if "floor" not in parts or "wall" not in parts:
            continue
        venue = rv.get(name) or rv.get(name.replace("/", "-")) or (sv if not rv else None)
        if venue == "clinic-reception":
            yield name, parts


def apply(plans):
    if os.environ.get("ROOM_CLINIC_LOBBY") != "1":
        return 0
    done = 0
    for name, parts in _rooms(plans):
        fp = [parts["floor"].matrix_world @ Vector(c) for c in parts["floor"].bound_box]
        x0, x1, y0, y1 = min(p.x for p in fp), max(p.x for p in fp), min(p.y for p in fp), max(p.y for p in fp)
        fz = max(p.z for p in fp)
        zc = max((parts["wall"].matrix_world @ Vector(c)).z for c in parts["wall"].bound_box)
        inside = lambda t: x0 - 0.2 <= t.x <= x1 + 0.2 and y0 - 0.2 <= t.y <= y1 + 0.2
        removed = 0
        for o in list(bpy.data.objects):
            t = o.matrix_world.translation
            if not inside(t) or t.z < fz + 2.0 or o.name.endswith(".ceiling") or o.name.endswith(".wall"):
                continue
            base = o.name.split("(")[0]
            if base in REMOVE_BASES or o.type == "LIGHT" or "LampFactory" in base or "CeilingLight" in base or (o.type == "MESH" and "Ceiling" in base):
                bpy.data.objects.remove(o, do_unlink=True); removed += 1
        W, D = x1 - x0, y1 - y0; cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        white = _mat("ir_cl_cove_white", (0.9, 0.88, 0.84), 0.85); glow = _mat("ir_cl_cove_glow", WARM, 0.5, 6.0); cream = _mat("ir_cl_pendant_cream", (0.88, 0.84, 0.74), 0.7)
        pend_glow = _mat("ir_cl_pendant_glow", WARM, 0.5, 5.0); wire = _mat("ir_cl_pendant_wire", (0.1, 0.1, 0.1), 0.5)
        panel_w, panel_h = W - 1.8, D - 1.8
        inner = _rrect(cx, cy, panel_w, panel_h, 0.9); ring_o = _rrect(cx, cy, panel_w + 0.28, panel_h + 0.28, 1.04)
        zp = zc - 0.07
        _panel(f"LobbyCoveFactory({name}).spawn_asset(panel)", inner, zp, white)
        _band(f"LobbyCoveFactory({name}).spawn_asset(glow)", ring_o, inner, zp + 0.005, glow)
        for k, (ux, uy) in enumerate(((0.25, 0.25), (0.75, 0.25), (0.25, 0.75), (0.75, 0.75))):
            ld = bpy.data.lights.new(f"ir_lobby_cove_{k}", "AREA"); ld.shape = "RECTANGLE"; ld.size = 1.0; ld.size_y = 1.0; ld.energy = 55.0; ld.color = (1.0, 0.82, 0.62)
            lo = bpy.data.objects.new(f"PointLampFactory(cove).spawn_asset({name}_{k})", ld); bpy.context.scene.collection.objects.link(lo)
            lo.location = (x0 + ux * W, y0 + uy * D, zp - 0.05); lo.rotation_euler = (math.pi, 0, 0)
        # three round pendants over the desk
        desk = next((o for o in bpy.data.objects if o.name.startswith("OakLouverDeskFactory") and inside(o.matrix_world.translation)), None)
        pend = 0
        if desk is not None:
            mw = desk.matrix_world; ax = (mw.to_3x3() @ Vector((0, 1, 0))); ax.z = 0; ax.normalize()
            base = Vector((mw.translation.x, mw.translation.y, 0)); half = min(1.2, desk.dimensions[1] / 2 - 0.5)
            for k, dv in enumerate((-half, 0.0, half)):
                p = base + ax * dv; zb = fz + 1.95
                _cyl(f"LobbyPendantFactory({name}).spawn_asset({k})", (p.x, p.y, zb), 0.12, 0.22, cream)
                _cyl(f"LobbyPendantFactory({name}).spawn_asset(g{k})", (p.x, p.y, zb - 0.005), 0.1, 0.012, pend_glow)
                _cyl(f"LobbyPendantFactory({name}).spawn_asset(w{k})", (p.x, p.y, (zb + 0.22 + zp) / 2), 0.003, zp - (zb + 0.22), wire)
                ld = bpy.data.lights.new(f"ir_lobby_pendant_{k}", "POINT"); ld.energy = 22.0; ld.color = (1.0, 0.78, 0.5); ld.shadow_soft_size = 0.1
                lo = bpy.data.objects.new(f"PointLampFactory(pendant).spawn_asset({name}_{k})", ld); bpy.context.scene.collection.objects.link(lo)
                lo.location = (p.x, p.y, zb - 0.15)
                pend += 1
        print(f"CLINIC_LOBBY_CEILING {name} removed={removed} pendants={pend} size={W:.1f}x{D:.1f}", flush=True)
        done += 1
    return done


def _cyl(name, c, r, h, mat, n=20):
    import bmesh
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=n, radius1=r, radius2=r, depth=h)
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free(); me.materials.append(mat)
    o = bpy.data.objects.new(name, me); bpy.context.scene.collection.objects.link(o); o.location = c
    return o
