"""Glass-pavilion shell for the rooftop fine-dining restaurant (reference set rooftop_restaurant_01; proposal docs/rooftop_fine_dining_design_proposal.md).

    shell_services(L, S, z_eave, z_ridge, at, name, rng, stats, room=None)     called by architecture_pass.build() when the archetype has rooftop=1
    light_chandelier(obj, warm_w=60.0)                                         turn a Poly Haven chandelier's bulb materials emissive + one warm light
    make_skyline_png(path)                                                     a dusk city-skyline card (generated, no real photo)

What it builds (room frame: u along the long axis, v across; the far long wall v = S is the glass side):
  * white steel roof trusses every 3 m (two top chords to a ridge at v = S/2, a bottom tie, a king post and two struts), purlins every ~1.2 m along
    each slope, and translucent roof panels between them
  * a glass curtain wall on the far long wall: wall faces in that band are removed from `<room>.wall`, white mullions every 1.2 m, two transoms,
    thin glass panes
  * a skyline card 45 m outside the glass (emissive texture) so the windows show a city at dusk
Trusses, purlins and mullions are one merged mesh each (steel is Principled white paint, so albedo / roughness / metallic GT read normally); the
panes and roof panels are thin Principled with transmission, i.e. 'glass' in the GT.
The record of drape anchors (u, z) on the trusses goes to stats['rooftop']['anchors'] for the cloth drape step.
"""
from __future__ import annotations

import math
import os
import random
from pathlib import Path

import bmesh
import bpy
from mathutils import Vector

from room_planner import proc_boutique_flagship as fl

SKYLINE = Path("/jarvis/project/robomituba/data/venue_refs/rooftop_refs/skyline_dusk.png")


def make_skyline_png(path=SKYLINE, w=4096, h=640, seed=7):
    from PIL import Image, ImageDraw
    rng = random.Random(seed)
    im = Image.new("RGB", (w, h)); d = ImageDraw.Draw(im)
    for y in range(h):                                       # sunset gradient: deep blue-violet top, warm orange-pink glow at the horizon
        t = (y / h) ** 1.4
        d.line((0, y, w, y), fill=(int(70 + 185 * t), int(60 + 120 * t), int(120 + 40 * t - 60 * t * t)))
    for layer, (base, col, hmax) in enumerate(((h - 40, (150, 110, 110), 110), (h - 10, (96, 70, 84), 150), (h, (52, 40, 58), 190))):
        x = 0
        while x < w:
            bw = rng.randint(40, 130); bh = rng.randint(60, hmax)
            top = base - bh
            d.rectangle((x, top, x + bw, h), fill=col)
            if layer >= 1:                                   # lit windows
                for wy in range(top + 8, h - 8, 16):
                    for wx in range(x + 6, x + bw - 6, 14):
                        if rng.random() < 0.22:
                            d.rectangle((wx, wy, wx + 6, wy + 8), fill=(255, 214, 140) if rng.random() < 0.7 else (200, 230, 255))
            x += bw + rng.randint(0, 14)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    im.save(path)
    return path


#: glass panes are closed slabs of this thickness (m). A zero-thickness glass plane has no back face: Mitsuba's dielectric then refracts it into a round fisheye and it blocks nothing physically
#: (user 2026-10-26: "0 mm glass must not be made"; thindielectric has no polarised variant, so a 6 mm closed slab with dielectric 1.5 is the supported form). ROOM_GLASS_THICK=0 restores the old plane.
GLASS_THICK = float(os.environ.get("ROOM_GLASS_THICK", "0.006"))


def _quads(name, quads, mat, thick=0.0):
    """One object from world-space quads [(p0, p1, p2, p3)] with unit UVs. thick > 0: each quad becomes a closed slab centred on the quad (front and back faces keep the UVs)."""
    bm = bmesh.new(); uv = bm.loops.layers.uv.verify()
    for q in quads:
        if thick > 0:
            p0, p1, p2, p3 = [Vector(p) for p in q]; n = (p1 - p0).cross(p3 - p0)
            if n.length < 1e-9:
                continue
            h = n.normalized() * (thick / 2)
            top = [bm.verts.new(p + h) for p in (p0, p1, p2, p3)]; bot = [bm.verts.new(p - h) for p in (p0, p1, p2, p3)]
            fs = [bm.faces.new(top), bm.faces.new(bot[::-1])] + [bm.faces.new([top[i], bot[i], bot[(i + 1) % 4], top[(i + 1) % 4]]) for i in range(4)]
            for lp, c in zip(fs[0].loops, ((0, 0), (1, 0), (1, 1), (0, 1))):
                lp[uv].uv = c
            for lp, c in zip(fs[1].loops, ((0, 0), (0, 1), (1, 1), (1, 0))):
                lp[uv].uv = c
            continue
        f = bm.faces.new([bm.verts.new(p) for p in q])
        for lp, c in zip(f.loops, ((0, 0), (1, 0), (1, 1), (0, 1))):
            lp[uv].uv = c
    if thick > 0:
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free(); me.materials.append(mat)
    o = bpy.data.objects.new(name, me); bpy.context.scene.collection.objects.link(o)
    return o


#: how much direct light the roof panels let through (RGB): a dusk-blue grey, so the room is lit by the chandeliers and warm fill, not by daylight
ROOF_ATTEN = (0.55, 0.36, 0.2)


def shadow_pass(m, atten=(1.0, 1.0, 1.0)):
    """Let shadow rays through a glass material (Mix of the Principled glass and a Transparent BSDF by Light Path > Is Shadow Ray). Without it a
    roof of transmissive panels blocks the sun and the sky for direct lighting and the room renders black (checked in a real room blend)."""
    nt = m.node_tree; N, L = nt.nodes, nt.links
    b = N["Principled BSDF"]; out = next(n for n in N if n.type == "OUTPUT_MATERIAL")
    lp = N.new("ShaderNodeLightPath"); tr = N.new("ShaderNodeBsdfTransparent"); mx = N.new("ShaderNodeMixShader")
    tr.inputs["Color"].default_value = (*atten, 1.0)             # what a shadow ray keeps of the light: <1 darkens the direct light behind the panel
    L.new(lp.outputs["Is Shadow Ray"], mx.inputs["Fac"]); L.new(b.outputs["BSDF"], mx.inputs[1]); L.new(tr.outputs["BSDF"], mx.inputs[2])
    L.new(mx.outputs["Shader"], out.inputs["Surface"])


def _glass(name, rough=0.0, tint=(0.9, 0.97, 1.0), transmission=1.0, atten=(1.0, 1.0, 1.0)):
    pa = fl._pa()
    m = bpy.data.materials.get(name)
    if m is not None:
        return m
    m = bpy.data.materials.new(name); m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*tint, 1); b.inputs["Roughness"].default_value = rough
    b.inputs["Transmission Weight"].default_value = transmission; b.inputs["IOR"].default_value = float(os.environ.get("ROOM_GLASS_IOR", "1.03"))     # a single-quad pane has no back face: IOR 1.45 bent everything seen through it (O2 r7 AST-02 'bowed mullions, diagonal posts'); ~1.0 = thin glass
    shadow_pass(m, atten)
    return m


def open_wall(wall_obj, at, S, z_top, margin_u=(1.0, 1.0), L=None, band=0.35):
    """Delete the faces of the room's wall mesh that lie on the far long wall (v ~ S) between margins and below z_top: the glass wall's opening."""
    if wall_obj is None or wall_obj.type != "MESH":
        return 0
    o0 = Vector((*at(0, 0), 0)); ux = Vector((*at(1, 0), 0)) - o0; vx = Vector((*at(0, 1), 0)) - o0
    bm = bmesh.new(); bm.from_mesh(wall_obj.data)
    mw = wall_obj.matrix_world
    kill = []
    for f in bm.faces:
        c = mw @ f.calc_center_median()
        d = c - o0
        u, v = d.dot(ux), d.dot(vx)
        if abs(v - S) < band and margin_u[0] < u < (L - margin_u[1] if L else 1e9) and 0.02 < c.z < z_top:
            kill.append(f)
    bmesh.ops.delete(bm, geom=kill, context="FACES")
    bm.to_mesh(wall_obj.data); bm.free()
    return len(kill)


def strip_tops(obj, z_min):
    """Delete the upward-facing faces of a room mesh above z_min (the ceiling rim and the exterior shell's roof cap)."""
    if obj is None or obj.type != "MESH":
        return 0
    bm = bmesh.new(); bm.from_mesh(obj.data); mw = obj.matrix_world
    kill = [f for f in bm.faces if (mw @ f.calc_center_median()).z > z_min and (mw.to_3x3() @ f.normal).z > 0.7]
    bmesh.ops.delete(bm, geom=kill, context="FACES")
    bm.to_mesh(obj.data); bm.free()
    return len(kill)


def shell_services(L, S, z_eave, z_ridge, at, name, rng, stats, room=None, truss_pitch=3.0):
    """`room` is the Room name (e.g. "break-room_0/0"): its `.ceiling` object is removed and its `.wall` gets the glass opening."""
    pa = fl._pa()
    steel = fl._flat("ir_rt_steel_white", (0.9, 0.9, 0.88), 0.5)
    roof = _glass("ir_rt_roof_poly", rough=0.35, tint=(0.86, 0.88, 0.86), transmission=0.55, atten=ROOF_ATTEN)
    pane = _glass("ir_rt_glass", rough=0.0, atten=(0.9, 0.72, 0.55))
    mull = fl._flat("ir_rt_mullion", (0.92, 0.92, 0.9), 0.45)
    z0 = z_eave - 0.15
    if room:                                                   # the Infinigen room's flat ceiling goes: the trusses and roof panels are the ceiling
        ce = bpy.data.objects.get(f"{room}.ceiling")
        if ce is not None:
            bpy.data.objects.remove(ce, do_unlink=True)
    # --- roof trusses + purlins (merged) ---
    members, anchors, purl = [], [], []
    nt = max(2, int(L / truss_pitch) + 1)
    for k in range(nt):
        u = 0.3 + k * (L - 0.6) / (nt - 1)
        pts = lambda v, z: (*at(u, v), z)
        members += [("cyl", pts(0, z_eave), pts(S / 2, z_ridge), 0.05, 4), ("cyl", pts(S, z_eave), pts(S / 2, z_ridge), 0.05, 4),
                    ("cyl", pts(0, z0), pts(S, z0), 0.04, 4), ("cyl", pts(S / 2, z0), pts(S / 2, z_ridge), 0.035, 4),
                    ("cyl", pts(S * 0.25, z0), pts(S / 2, z_ridge), 0.03, 4), ("cyl", pts(S * 0.75, z0), pts(S / 2, z_ridge), 0.03, 4)]
        anchors += [(round(u, 2), round(z_ridge - 0.1, 2))]
    nsl = max(3, int((S / 2) / 1.2))
    for side in (0, 1):
        for j in range(nsl + 1):
            t = j / nsl
            v = (S / 2) * t if side == 0 else S - (S / 2) * t
            z = z_eave + (z_ridge - z_eave) * t
            purl.append(("cyl", (*at(0.1, v), z), (*at(L - 0.1, v), z), 0.03, 4))
    fl.mesh_object(name("RoofTruss"), [(steel, members + purl)], bevel=False)
    # --- translucent roof panels (two slopes) ---
    quads = []
    for side in (0, 1):
        for iu in range(int(L / 1.5)):
            u0, u1 = iu * 1.5 + 0.1, min(L - 0.1, (iu + 1) * 1.5 - 0.05)
            for j in range(nsl):
                t0, t1 = j / nsl, (j + 1) / nsl
                va, vb = ((S / 2) * t0, (S / 2) * t1) if side == 0 else (S - (S / 2) * t0, S - (S / 2) * t1)
                za, zb = z_eave + (z_ridge - z_eave) * t0 + 0.02, z_eave + (z_ridge - z_eave) * t1 + 0.02
                quads.append(((*at(u0, va), za), (*at(u1, va), za), (*at(u1, vb), zb), (*at(u0, vb), zb)))
    _quads(name("RoofPanels"), quads, roof)
    # --- glass curtain wall on the far long wall (v = S) ---
    removed = open_wall(bpy.data.objects.get(f"{room}.wall") if room else None, at, S, z_eave, margin_u=(0.8, 0.8), L=L)
    if room:                                                   # the exterior shell (rendered, no openings of its own) would still close the roof and the glass wall
        ext = bpy.data.objects.get(f"{room}.exterior")
        removed += open_wall(ext, at, S, z_eave + 0.3, margin_u=(0.8, 0.8), L=L, band=0.7)
        strip_tops(ext, z_eave - 0.3)
        strip_tops(bpy.data.objects.get(f"{room}.wall"), z_eave - 0.3)
    nm = max(2, int((L - 1.6) / 1.2) + 1)
    mull_parts, panes = [], []
    vS = S - 0.04
    for k in range(nm):
        u = 0.8 + k * (L - 1.6) / (nm - 1)
        mull_parts.append(("box", *at(u, vS), z_eave / 2, 0.06 if abs(at(1, 0)[0] - at(0, 0)[0]) < 1e-9 else 0.06, 0.06, z_eave))
    for zt in (0.05, 2.4, z_eave - 0.03):
        a, b = at(0.8, vS), at(L - 0.8, vS)
        mull_parts.append(("box", (a[0] + b[0]) / 2, (a[1] + b[1]) / 2, zt, abs(b[0] - a[0]) + 0.06, abs(b[1] - a[1]) + 0.06, 0.06))
    fl.mesh_object(name("Mullions"), [(mull, mull_parts)], bevel=False)
    for k in range(nm - 1):
        u0 = 0.8 + k * (L - 1.6) / (nm - 1); u1 = 0.8 + (k + 1) * (L - 1.6) / (nm - 1)
        for z0_, z1_ in ((0.08, 2.37), (2.43, z_eave - 0.06)):
            quads_p = ((*at(u0 + 0.03, vS), z0_), (*at(u1 - 0.03, vS), z0_), (*at(u1 - 0.03, vS), z1_), (*at(u0 + 0.03, vS), z1_))
            panes.append(quads_p)
    _quads(name("GlassPanes"), panes, pane)
    # --- skyline card outside the glass ---
    if not SKYLINE.exists():
        make_skyline_png()
    cm = bpy.data.materials.new("ir_rt_skyline"); cm.use_nodes = True
    nt_ = cm.node_tree; b = nt_.nodes["Principled BSDF"]
    t = nt_.nodes.new("ShaderNodeTexImage"); t.image = bpy.data.images.load(str(SKYLINE), check_existing=True)
    nt_.links.new(t.outputs["Color"], b.inputs["Base Color"]); nt_.links.new(t.outputs["Color"], b.inputs["Emission Color"])
    b.inputs["Emission Strength"].default_value = 2.4; b.inputs["Base Color"].default_value = (0, 0, 0, 1); b.inputs["Roughness"].default_value = 1.0
    card_v, H_ = S + 45.0, 26.0
    cq = ((*at(-80, card_v), -3.0), (*at(L + 80, card_v), -3.0), (*at(L + 80, card_v), H_ - 3.0), (*at(-80, card_v), H_ - 3.0))
    _quads(name("SkylineCard"), [cq], cm)
    stats["rooftop"] = {"trusses": nt, "anchors": anchors, "wall_faces_removed": removed, "mullions": nm, "ceiling_removed": bool(room)}
    if os.environ.get("ROOM_ROOFTOP_DRAPES", "1") != "0" and anchors:      # cloth-simulated sheer swags between the trusses (baked meshes)
        try:
            from room_planner import rooftop_drape
            rooftop_drape.drape_services(L, z_eave - 0.2, S / 2, anchors, at, name, rng, stats)
        except Exception as ex:                                  # noqa: BLE001 -- a failed simulation must not fail the scene
            stats["rooftop"]["drape_error"] = str(ex)[:80]


def light_chandelier(obj, warm_w=60.0):
    """Make a Poly Haven chandelier glow: materials named *lamp* / *bulb* get a warm emission, plus one point light at the object's centre."""
    n = 0
    for slot in obj.material_slots:
        m = slot.material
        if m and m.use_nodes and any(k in m.name.lower() for k in ("lamp", "bulb")):
            b = m.node_tree.nodes.get("Principled BSDF")
            if b is not None:
                b.inputs["Emission Color"].default_value = (1.0, 0.72, 0.42, 1.0); b.inputs["Emission Strength"].default_value = 9.0; n += 1
    ld = bpy.data.lights.new("ir_chandelier_light", "POINT"); ld.energy = warm_w; ld.color = (1.0, 0.74, 0.46); ld.shadow_soft_size = 0.15
    lo = bpy.data.objects.new(f"PointLampFactory(chandelier).spawn_asset({obj.name})", ld); bpy.context.scene.collection.objects.link(lo)
    lo.parent = obj; lo.location = (0, 0, obj.dimensions[2] * 0.45 if obj.dimensions[2] else 0.4)
    return n
