"""Octagonal domed rotunda shell for the science-museum scene (docs/space_museum_design_proposal.md). Infinigen rooms are rectangles, so the rotunda is built INSIDE the
room as new meshes and the room's own ceiling is removed:

    shell_services(L, S, zc, at, name, rng, stats, room=None)      called by architecture_pass.build() when the archetype has museum=1

  * 8 travertine wall panels (octagon, circumradius R = min(L, S) / 2 - 0.35) up to z_cornice = 0.62 zc, each with a hexagonal dark grille window, pilasters at the
    8 corners and a gilt cornice ring
  * a frieze band (8 panels, generated abstract art frieze_0..7.png) from z_cornice to 0.8 zc
  * a dome: 8 sectors x 12 rings rising from 0.8 zc to zc, textured with the generated fresco (fresco_dome.png), with a central oculus (circle hole, a brass ring) and
    an emissive warm cove ring at the base of the dome
  * a circular floor opening: the floor is NOT cut (it is the room floor); a RotundaRail ring is placed by the layout around the opening position at the centre
The room's `.ceiling` object is removed; the museum art images come from data/venue_refs/museum_art (gen_museum_art.py).
"""
from __future__ import annotations

import math
from pathlib import Path

import bmesh
import bpy
from mathutils import Vector

from room_planner import proc_boutique_flagship as fl

ART = Path("/jarvis/project/robomituba/data/venue_refs/museum_art")


def _img_mat(name, file, rough=0.7, emit=0.0):
    m = bpy.data.materials.get(name)
    if m is not None:
        return m
    m = bpy.data.materials.new(name); m.use_nodes = True
    nt = m.node_tree; b = nt.nodes["Principled BSDF"]
    t = nt.nodes.new("ShaderNodeTexImage"); t.image = bpy.data.images.load(str(ART / file), check_existing=True)
    nt.links.new(t.outputs["Color"], b.inputs["Base Color"]); b.inputs["Roughness"].default_value = rough
    if emit:
        nt.links.new(t.outputs["Color"], b.inputs["Emission Color"]); b.inputs["Emission Strength"].default_value = emit
    return m


def _travertine():
    """Procedural travertine (replaces the stone scan, whose halved contrast read flat): horizontal veining (noise stretched 8x along z, two scales), pale / warm tonal bands, and
    a dressed-stone joint pattern every 0.6 m in height x 1.2 m along the wall as a shallow bump + darker mortar (brick texture on (x + y, z)). All object coordinates, so
    walls, columns, pilasters and cladding share the pattern."""
    m = bpy.data.materials.get("ir_mu_travertine_proc")
    if m is not None:
        return m
    m = bpy.data.materials.new("ir_mu_travertine_proc"); m.use_nodes = True; N, Lk = m.node_tree.nodes, m.node_tree.links; b = N["Principled BSDF"]
    tc = N.new("ShaderNodeTexCoord"); sep = N.new("ShaderNodeSeparateXYZ"); Lk.new(tc.outputs["Object"], sep.inputs[0])
    sxy = N.new("ShaderNodeMath"); sxy.operation = "ADD"; Lk.new(sep.outputs["X"], sxy.inputs[0]); Lk.new(sep.outputs["Y"], sxy.inputs[1])
    cb = N.new("ShaderNodeCombineXYZ"); Lk.new(sxy.outputs["Value"], cb.inputs["X"]); Lk.new(sep.outputs["Z"], cb.inputs["Y"])
    mp = N.new("ShaderNodeMapping"); mp.inputs["Scale"].default_value = (1.0, 1.0, 8.0)                      # veins run horizontally: fast variation in z, slow along the wall
    Lk.new(tc.outputs["Object"], mp.inputs["Vector"])
    n1 = N.new("ShaderNodeTexNoise"); n1.inputs["Scale"].default_value = 1.4; n1.inputs["Detail"].default_value = 6; n1.inputs["Roughness"].default_value = 0.6; Lk.new(mp.outputs["Vector"], n1.inputs["Vector"])
    n2 = N.new("ShaderNodeTexNoise"); n2.inputs["Scale"].default_value = 6.0; n2.inputs["Detail"].default_value = 3; Lk.new(mp.outputs["Vector"], n2.inputs["Vector"])
    mx = N.new("ShaderNodeMixRGB"); mx.blend_type = "MIX"; mx.inputs["Fac"].default_value = 0.25; Lk.new(n1.outputs["Color"], mx.inputs["Color1"]); Lk.new(n2.outputs["Color"], mx.inputs["Color2"])
    rp = N.new("ShaderNodeValToRGB"); rp.color_ramp.elements[0].position = 0.4; rp.color_ramp.elements[1].position = 0.6
    rp.color_ramp.elements[0].color = (0.84, 0.75, 0.58, 1); rp.color_ramp.elements[1].color = (0.96, 0.91, 0.79, 1); Lk.new(mx.outputs["Color"], rp.inputs["Fac"])
    br = N.new("ShaderNodeTexBrick"); br.offset = 0.5; br.squash = 1.0
    br.inputs["Scale"].default_value = 1.0; br.inputs["Brick Width"].default_value = 2.4; br.inputs["Row Height"].default_value = 1.2; br.inputs["Mortar Size"].default_value = 0.01; br.inputs["Mortar Smooth"].default_value = 0.4
    br.inputs["Color1"].default_value = (1, 1, 1, 1); br.inputs["Color2"].default_value = (0.96, 0.96, 0.96, 1); br.inputs["Mortar"].default_value = (0.35, 0.3, 0.25, 1); Lk.new(cb.outputs["Vector"], br.inputs["Vector"])
    mul = N.new("ShaderNodeMixRGB"); mul.blend_type = "MULTIPLY"; mul.inputs["Fac"].default_value = 1.0; Lk.new(rp.outputs["Color"], mul.inputs["Color1"]); Lk.new(br.outputs["Color"], mul.inputs["Color2"])
    Lk.new(mul.outputs["Color"], b.inputs["Base Color"]); b.inputs["Roughness"].default_value = 0.5
    bp = N.new("ShaderNodeBump"); bp.inputs["Strength"].default_value = 0.6; bp.inputs["Distance"].default_value = 0.01; Lk.new(br.outputs["Fac"], bp.inputs["Height"]); Lk.new(bp.outputs["Normal"], b.inputs["Normal"])
    return m


def _mesh(name, bm, mats):
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    for m in mats:
        me.materials.append(m)
    o = bpy.data.objects.new(name, me); bpy.context.scene.collection.objects.link(o)
    return o


def _quad(bm, uv, pts, uvs, mat_index=0):
    f = bm.faces.new([bm.verts.new(p) for p in pts]); f.material_index = mat_index
    for lp, c in zip(f.loops, uvs):
        lp[uv].uv = c
    return f


def shell_services(L, S, zc, at, name, rng, stats, room=None):
    cv = S / 2
    from room_planner.museum_layout import rotunda_radius
    R = rotunda_radius(L, S)
    cu = R + 0.35                                                                  # the rotunda sits at the entrance end; cv stays mid-width
    zc_ = max(zc, 4.0)
    zc1, zf0, zf1, zd = 0.62 * zc_, 0.62 * zc_, 0.8 * zc_, zc_
    ang = [math.pi / 8 + k * math.pi / 4 for k in range(8)]                          # 8 corners of the octagon (flat faces toward the axes)
    P = [(cu + R * math.cos(a), cv + R * math.sin(a)) for a in ang]
    W = lambda u, v, z: (*at(u, v), z)
    if room:
        ce = bpy.data.objects.get(f"{room}.ceiling")
        if ce is not None:
            bpy.data.objects.remove(ce, do_unlink=True)
    trav, gilt = _travertine(), fl._flat("ir_mu_gilt_cornice", (0.8, 0.62, 0.25), 0.3, 1.0)
    grille = fl._flat("ir_mu_grille", (0.07, 0.05, 0.04), 0.5, 0.6)
    # recessed vaulted corridor behind the doorway of the -v axis panel (k = 5): a barrel-vaulted tunnel with a lit end, as deep as the gap to the room wall allows (S25 A/B: 'deep arched entrance corridor')
    KC = 5; CORR_W, CORR_H = 2.2, 3.4
    CORR_D = 0.0                                                                       # the dead-end tunnel is off: the user wants CONNECTED rooms (S25 note)
    OPEN = {7: (2.8, 3.8), 0: (2.0, 3.2), 6: (2.0, 3.2)}                               # real arched openings from the rotunda into the exhibit / video hall (panel 7 = the +u axis, 0 and 6 = the diagonals toward the strip)
    # ---- walls + pilasters + cornice ----
    bm = bmesh.new(); uv = bm.loops.layers.uv.verify()
    for k in range(8):
        (u0, v0), (u1, v1) = P[k], P[(k + 1) % 8]
        if k in OPEN:                                                                   # an open panel: a doorway opening (left / right / top pieces)
            ow, oh = OPEN[k]
            seg_ = math.hypot(u1 - u0, v1 - v0); tl, tr = 0.5 - ow / 2 / seg_, 0.5 + ow / 2 / seg_
            Pt = lambda t_: (u0 + (u1 - u0) * t_, v0 + (v1 - v0) * t_)
            _quad(bm, uv, (W(u0, v0, 0), W(*Pt(tl), 0), W(*Pt(tl), zc1), W(u0, v0, zc1)), ((0, 0), (tl, 0), (tl, 1), (0, 1)))
            _quad(bm, uv, (W(*Pt(tr), 0), W(u1, v1, 0), W(u1, v1, zc1), W(*Pt(tr), zc1)), ((tr, 0), (1, 0), (1, 1), (tr, 1)))
            zs0 = oh - ow / 2                                                           # arched opening: the wall above the arch is one polygon (arc + top edge)
            arc = [(0.5 + (ow / 2) * math.cos(math.pi * i / 12) / seg_, zs0 + (ow / 2) * math.sin(math.pi * i / 12)) for i in range(12, -1, -1)]   # left springline -> crown -> right
            poly = [W(*Pt(t_), z_) for t_, z_ in arc] + [W(*Pt(tr), zc1), W(*Pt(tl), zc1)]
            f_ = bm.faces.new([bm.verts.new(p_) for p_ in poly])
            for lp_, p_ in zip(f_.loops, poly):
                lp_[uv].uv = (0.5, 0.5)
            continue
        _quad(bm, uv, (W(u0, v0, 0), W(u1, v1, 0), W(u1, v1, zc1), W(u0, v0, zc1)), ((0, 0), (1, 0), (1, 1), (0, 1)))
    fl_parts = []
    for k in range(8):
        u, v = P[k]
        x_, y_ = at(u, v)                                                                   # thick engaged columns at the octagon corners (S25: 'lacks thick travertine columns')
        fl_parts += [("cyl", (x_, y_, 0.0), (x_, y_, zc1), 0.44, 20), ("box", x_, y_, 0.12, 1.05, 1.05, 0.24), ("box", x_, y_, zc1 - 0.14, 1.1, 1.1, 0.28)]
    wall = _mesh(name("RotundaWalls"), bm, [trav])
    fl.mesh_object(name("RotundaPilasters"), [(trav, fl_parts)], bevel=False)
    # cornice ring (gilt) and grille windows
    ring, win, arches = [], [], []
    for k in range(8):
        (u0, v0), (u1, v1) = P[k], P[(k + 1) % 8]
        um, vm = (u0 + u1) / 2, (v0 + v1) / 2; yaw = math.atan2(v1 - v0, u1 - u0)
        ring.append(("cyl", W(u0, v0, zc1 + 0.04), W(u1, v1, zc1 + 0.04), 0.06, 8))
        ring.append(("cyl", W(u0, v0, zf1 + 0.04), W(u1, v1, zf1 + 0.04), 0.07, 8))
        arches.append((k, um, vm, yaw))
    fl.mesh_object(name("RotundaCornice"), [(gilt, ring)], bevel=False)
    # arched niches (even panels) and moulded doorways (odd panels): a dark recess, a gilt arch / lintel moulding, pilaster-like jambs
    bronze = fl._flat("ir_mu_door_bronze", (0.16, 0.11, 0.07), 0.4, 0.7); void = fl._flat("ir_mu_niche_dark", (0.03, 0.025, 0.02), 0.8)
    rec, mould, jamb = [], [], []
    for k, um, vm, yaw in arches:
        if k in OPEN:                                                                          # a real opening here: gilt arch + bronze jambs, no painted recess
            ow, oh = OPEN[k]; nx_, ny_ = at(um + (cu - um) * 0.045, vm + (cv - vm) * 0.045); tx_, ty_ = math.cos(yaw), math.sin(yaw)
            for sgn in (-1, 1):
                jamb.append(("box", nx_ + sgn * tx_ * (ow / 2 + 0.07), ny_ + sgn * ty_ * (ow / 2 + 0.07), (oh - ow / 2) / 2, 0.1, 0.14, oh - ow / 2, yaw + math.pi / 2))
            for j in range(13):
                a_ = math.pi * j / 12; mould.append(("box", nx_ + tx_ * math.cos(a_) * (ow / 2 + 0.07), ny_ + ty_ * math.cos(a_) * (ow / 2 + 0.07), oh - ow / 2 + math.sin(a_) * (ow / 2 + 0.07), 0.12, 0.16, 0.16, yaw + math.pi / 2))
            continue
        ex, ey = at(um + (cu - um) * 0.02, vm + (cv - vm) * 0.02); nx, ny = at(um + (cu - um) * 0.045, vm + (cv - vm) * 0.045); tx, ty = math.cos(yaw), math.sin(yaw)
        # `at` maps (u, v) -> world; the panel tangent in world is (cos, sin of yaw) in the room frame (long_x frame: at(u, v) = (x0 + u, y0 + v))
        w_, h_ = (1.7, 2.6) if k % 2 else (1.5, 3.3)
        rec.append(("box", ex, ey, h_ / 2, 0.04, w_, h_, yaw + math.pi / 2))
        for sgn in (-1, 1):
            jamb.append(("box", nx + sgn * tx * (w_ / 2 + 0.07), ny + sgn * ty * (w_ / 2 + 0.07), h_ / 2, 0.1, 0.14, h_ + 0.1, yaw + math.pi / 2))
        if k % 2:
            mould.append(("box", nx, ny, h_ + 0.08, 0.12, w_ + 0.4, 0.16, yaw + math.pi / 2))                    # lintel
        else:
            for j in range(13):                                                                                  # semicircular arch of boxes over a 3.3 m jamb height
                a_ = math.pi * j / 12; cxh = math.cos(a_) * (w_ / 2 + 0.07); czh = h_ - 0.3 + math.sin(a_) * (w_ / 2 + 0.07)
                mould.append(("box", nx + tx * cxh, ny + ty * cxh, czh, 0.12, 0.16, 0.16, yaw + math.pi / 2 + a_ - math.pi / 2 + math.pi / 2 * 0))
    niche = bpy.data.materials.get("ir_mu_niche_glow") or bpy.data.materials.new("ir_mu_niche_glow"); niche.use_nodes = True
    nb = niche.node_tree.nodes["Principled BSDF"]; nb.inputs["Base Color"].default_value = (0.8, 0.62, 0.38, 1); nb.inputs["Emission Color"].default_value = (1.0, 0.8, 0.52, 1); nb.inputs["Emission Strength"].default_value = 0.9
    fl.mesh_object(name("RotundaRecesses"), [(niche, rec)], bevel=False)                    # lit alcoves, not dark doors
    fl.mesh_object(name("RotundaJambs"), [(bronze, jamb)], bevel=False)
    fl.mesh_object(name("RotundaMouldings"), [(gilt, mould)], bevel=False)
    if CORR_D > 1.0:
        k = KC; (u0, v0), (u1, v1) = P[k], P[(k + 1) % 8]; um_, vm_ = (u0 + u1) / 2, (v0 + v1) / 2
        nl_ = math.hypot(cu - um_, cv - vm_); nu_, nv_ = (cu - um_) / nl_, (cv - vm_) / nl_; tx_, ty_ = -nv_, nu_
        Q = lambda s_, d_, z_: W(um_ + tx_ * s_ - nu_ * d_, vm_ + ty_ * s_ - nv_ * d_, z_)           # s: sideways, d: depth behind the panel, z: height
        zs_ = CORR_H - CORR_W / 2; wc = CORR_W / 2
        plaster = fl._flat("ir_mu_corr_plaster", (0.72, 0.6, 0.42), 0.8); floor_m = fl._flat("ir_mu_corr_floor", (0.14, 0.1, 0.07), 0.3)
        endm = bpy.data.materials.get("ir_mu_corr_end") or bpy.data.materials.new("ir_mu_corr_end"); endm.use_nodes = True
        eb = endm.node_tree.nodes["Principled BSDF"]; eb.inputs["Base Color"].default_value = (1.0, 0.86, 0.6, 1); eb.inputs["Emission Color"].default_value = (1.0, 0.8, 0.5, 1); eb.inputs["Emission Strength"].default_value = 1.1
        def one(nm, quad, mat):
            bm_ = bmesh.new(); uv_ = bm_.loops.layers.uv.verify(); _quad(bm_, uv_, quad, ((0, 0), (1, 0), (1, 1), (0, 1))); _mesh(name(nm), bm_, [mat])
        one("CorridorFloor", (Q(-wc, 0, 0.005), Q(wc, 0, 0.005), Q(wc, CORR_D, 0.005), Q(-wc, CORR_D, 0.005)), floor_m)
        one("CorridorWallL", (Q(-wc, 0, 0), Q(-wc, CORR_D, 0), Q(-wc, CORR_D, zs_), Q(-wc, 0, zs_)), trav)
        one("CorridorWallR", (Q(wc, 0, 0), Q(wc, CORR_D, 0), Q(wc, CORR_D, zs_), Q(wc, 0, zs_)), trav)
        for j in range(12):                                                                        # the barrel vault: 12 segments over the springline
            a0, a1 = math.pi * j / 12, math.pi * (j + 1) / 12
            one("CorridorVault", (Q(wc * math.cos(a0), 0, zs_ + wc * math.sin(a0)), Q(wc * math.cos(a0), CORR_D, zs_ + wc * math.sin(a0)),
                                  Q(wc * math.cos(a1), CORR_D, zs_ + wc * math.sin(a1)), Q(wc * math.cos(a1), 0, zs_ + wc * math.sin(a1))), plaster)
        one("CorridorEnd", (Q(-wc, CORR_D, 0), Q(wc, CORR_D, 0), Q(wc, CORR_D, zs_), Q(-wc, CORR_D, zs_)), endm)
        one("CorridorEndTop", tuple(Q(wc * math.cos(math.pi * i / 12), CORR_D, zs_ + wc * math.sin(math.pi * i / 12)) for i in range(13)), endm)
        ex_, ey_ = at(um_ - nu_ * (CORR_D - 0.4), vm_ - nv_ * (CORR_D - 0.4))
        ld_ = bpy.data.lights.new("ir_mu_corridor", "POINT"); ld_.energy = 30.0; ld_.color = (1.0, 0.8, 0.52); ld_.shadow_soft_size = 0.4
        lo_ = bpy.data.objects.new("PointLampFactory(corridor).spawn_asset(mu_c)", ld_); bpy.context.scene.collection.objects.link(lo_); lo_.location = (ex_, ey_, 2.2)
        stats["corridor"] = {"depth": round(CORR_D, 2), "panel": KC}
    # hexagonal ventilation openings above every doorway/niche, a dark marble base band and vertical battens: relief on the flat travertine (S25 A/B)
    dark_m = fl._flat("ir_mu_base_marble", (0.11, 0.09, 0.07), 0.35); hex_f, hex_v, band, bat, hex_slats = [], [], [], [], []
    for k, um, vm, yaw in arches:
        nu, nv = cu - um, cv - vm; nl = math.hypot(nu, nv); nu, nv = nu / nl, nv / nl                      # unit vector from the panel into the room
        px, py = at(um + (cu - um) * 0.01, vm + (cv - vm) * 0.01); tx, ty = math.cos(yaw), math.sin(yaw)
        zh = 0.84 * zc1
        hex_f.append(("cyl", (px, py, zh), (px + nu * 0.07, py + nv * 0.07, zh), 0.46, 6))
        for dz in (-0.2, -0.1, 0.0, 0.1, 0.2):                                                            # louvre slats across the opening
            hex_slats.append(("box", px + nu * 0.1, py + nv * 0.1, zh + dz, 0.03, 0.6 * (1 - abs(dz) * 1.0), 0.025, yaw + math.pi / 2))
        hex_v.append(("cyl", (px + nu * 0.05, py + nv * 0.05, zh), (px + nu * 0.09, py + nv * 0.09, zh), 0.36, 6))
        seg = 0.765 * R
        if k not in OPEN:                                                                                 # no base band across an open doorway
            band.append(("box", px + nu * 0.03, py + nv * 0.03, 0.35, 0.06, seg * 0.98, 0.7, yaw + math.pi / 2))
        for f_ in (-0.36, 0.36):                                                                          # two battens per panel, clear of the doorway
            bat.append(("box", px + tx * seg * f_ + nu * 0.03, py + ty * seg * f_ + nv * 0.03, zc1 / 2, 0.06, 0.12, zc1, yaw + math.pi / 2))
    fl.mesh_object(name("RotundaHexFrames"), [(bronze, hex_f + hex_slats)], bevel=False)                # plain dark-bronze louvre, no gold (S25 A/B: 'over-decorative gold hex openings')
    fl.mesh_object(name("RotundaHexVents"), [(void, hex_v)], bevel=False)
    fl.mesh_object(name("RotundaBaseBand"), [(dark_m, band)], bevel=False)
    fl.mesh_object(name("RotundaBattens"), [(trav, bat)], bevel=False)
    # ---- frieze band: the generated mural strip repeated 3x round the octagon (UV u = 3k/8 .. 3(k+1)/8, texture repeat), else one abstract image per panel ----
    strip = (ART / "frieze_strip.png").exists()
    for k in range(8):
        (u0, v0), (u1, v1) = P[k], P[(k + 1) % 8]
        bm = bmesh.new(); uv = bm.loops.layers.uv.verify()
        if strip:
            ua_, ub_ = 3 * k / 8, 3 * (k + 1) / 8
            _quad(bm, uv, (W(u0, v0, zf0 + 0.08), W(u1, v1, zf0 + 0.08), W(u1, v1, zf1), W(u0, v0, zf1)), ((ua_, 0), (ub_, 0), (ub_, 1), (ua_, 1)))
            _mesh(name("FriezePanel"), bm, [_img_mat("ir_mu_frieze_strip", "frieze_strip.png", 0.6)])
        else:
            _quad(bm, uv, (W(u0, v0, zf0 + 0.08), W(u1, v1, zf0 + 0.08), W(u1, v1, zf1), W(u0, v0, zf1)), ((0, 0), (1, 0), (1, 1), (0, 1)))
            _mesh(name("FriezePanel"), bm, [_img_mat(f"ir_mu_frieze_{k % 8}", f"frieze_{k % 8}.png", 0.6)])
    # ---- dome: 8 sectors x 12 rings between the frieze top and the crown, textured with the fresco ----
    rings = 12; R0 = R * 0.97
    bm = bmesh.new(); uv = bm.loops.layers.uv.verify()
    def pt(k, j):
        t = j / rings; z = zf1 + (zd - zf1) * math.sin(t * math.pi / 2 * 0.98)
        r = R0 * math.cos(t * math.pi / 2 * 0.98) * (1 - 0.0) + 0.001
        a = k * math.pi / 4 * 1.0 + math.pi / 8
        return (cu + r * math.cos(a), cv + r * math.sin(a), z), (k / 8 * 8, 1 - t)
    seg = 32; a_of = lambda s: 2 * math.pi * s / seg
    for s in range(seg):
        for j in range(rings):
            def vtx(ss, jj):
                t = jj / rings; r = R0 * math.cos(t * math.pi / 2 * 0.97) + 0.45 * (jj == rings) ; z = zf1 + (zd - zf1) * math.sin(t * math.pi / 2 * 0.97)
                return (*at(cu + max(r, 0.45) * math.cos(a_of(ss)), cv + max(r, 0.45) * math.sin(a_of(ss))), z)
            _quad(bm, uv, (vtx(s, j), vtx(s + 1, j), vtx(s + 1, j + 1), vtx(s, j + 1)), ((s / seg, j / rings), ((s + 1) / seg, j / rings), ((s + 1) / seg, (j + 1) / rings), (s / seg, (j + 1) / rings)))
    for f in bm.faces:
        f.normal_flip()                                                                  # faces point inward (down into the hall)
    _mesh(name("RotundaDome"), bm, [_img_mat("ir_mu_fresco", "fresco_dome.png", 0.75, 0.55)])
    # ---- mosaic floor: the generated top-down mosaic as a disc decal (64-gon fan, UV from position) just above the room floor ----
    if (ART / "floor_mosaic.png").exists():
        fobj = bpy.data.objects.get(f"{room}.floor") if room else None
        fz = max(((fobj.matrix_world @ Vector(c)).z for c in fobj.bound_box), default=0.0) if fobj is not None else 0.0
        rd = 0.52 * R * math.cos(math.pi / 8); n_ = 64                                   # a modest rosette (S25 A/B: floor rosette overdone)
        bm = bmesh.new(); uv = bm.loops.layers.uv.verify(); c0 = bm.verts.new((*at(cu, cv), fz + 0.004))
        ring_v = [bm.verts.new((*at(cu + rd * math.cos(2 * math.pi * i / n_), cv + rd * math.sin(2 * math.pi * i / n_)), fz + 0.004)) for i in range(n_)]
        for i in range(n_):
            f = bm.faces.new((c0, ring_v[i], ring_v[(i + 1) % n_]))
            for lp, (px, py) in zip(f.loops, ((0, 0), (math.cos(2 * math.pi * i / n_) * rd, math.sin(2 * math.pi * i / n_) * rd), (math.cos(2 * math.pi * (i + 1) / n_) * rd, math.sin(2 * math.pi * (i + 1) / n_) * rd))):
                lp[uv].uv = (0.5 + px / (2 * rd), 0.5 + py / (2 * rd))
        _mesh(name("RotundaMosaic"), bm, [_img_mat("ir_mu_mosaic", "floor_mosaic.png", 0.2)])
    # ---- exhibit / video strip floor: the mosaic as square medallions down the middle of the strip (S25: 'empty cream floor') ----
    if (ART / "floor_mosaic.png").exists():
        fobj2 = bpy.data.objects.get(f"{room}.floor") if room else None
        fz2 = max(((fobj2.matrix_world @ Vector(c)).z for c in fobj2.bound_box), default=0.0) if fobj2 is not None else 0.0
        side_ = min(S * 0.3, 2.6); u_a, u_b = 2 * R + 0.35 + side_ / 2 + 0.2, L - side_ / 2 - 0.4; cnt = max(1, int((u_b - u_a) // (side_ + 0.5)) + 1) if u_b > u_a else 0
        mm = _img_mat("ir_mu_mosaic", "floor_mosaic.png", 0.2)
        for j in range(cnt):
            uc = u_a + (j * (u_b - u_a) / max(cnt - 1, 1) if cnt > 1 else (u_b - u_a) / 2); h_ = side_ / 2
            bm = bmesh.new(); uv = bm.loops.layers.uv.verify()
            _quad(bm, uv, ((*at(uc - h_, cv - h_), fz2 + 0.004), (*at(uc + h_, cv - h_), fz2 + 0.004), (*at(uc + h_, cv + h_), fz2 + 0.004), (*at(uc - h_, cv + h_), fz2 + 0.004)), ((0, 0), (1, 0), (1, 1), (0, 1)))
            _mesh(name("StripMosaic"), bm, [mm])
    # ---- warm cove ring at the dome base and a brass oculus ring ----
    glow = bpy.data.materials.get("ir_mu_cove_glow") or bpy.data.materials.new("ir_mu_cove_glow")
    glow.use_nodes = True; b = glow.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (1.0, 0.8, 0.5, 1); b.inputs["Emission Color"].default_value = (1.0, 0.78, 0.45, 1); b.inputs["Emission Strength"].default_value = 11.0
    cov = [("cyl", W(P[k][0] + (cu - P[k][0]) * 0.015, P[k][1] + (cv - P[k][1]) * 0.015, zf1 + 0.1), W(P[(k + 1) % 8][0] + (cu - P[(k + 1) % 8][0]) * 0.015, P[(k + 1) % 8][1] + (cv - P[(k + 1) % 8][1]) * 0.015, zf1 + 0.1), 0.09, 8) for k in range(8)]
    fl.mesh_object(name("DomeCove"), [(glow, cov)], bevel=False)
    for k in range(6):                                                                   # soft lights up in the dome: the fresco is lit by its cove
        a = k * math.pi / 3; x, y = at(cu + 0.7 * R * math.cos(a), cv + 0.7 * R * math.sin(a))
        ld = bpy.data.lights.new(f"ir_mu_dome_{k}", "AREA"); ld.shape = "RECTANGLE"; ld.size = 1.6; ld.size_y = 1.6; ld.energy = 34.0; ld.color = (1.0, 0.76, 0.5)
        lo = bpy.data.objects.new(f"PointLampFactory(dome).spawn_asset(mu_{k})", ld); bpy.context.scene.collection.objects.link(lo)
        lo.location = (x, y, zf1 + 0.5); lo.rotation_euler = (0, 0, 0)
    # soft lights over the exhibit / video strip beyond the rotunda (the room's own ceiling light is gone with the ceiling)
    n_u = max(2, int((L - 2 * R - 0.7) // 3.5))
    for iu in range(n_u):
        for iv in range(2):
            u = 2 * R + 0.7 + (iu + 0.5) * (L - 2 * R - 0.7) / n_u; v = S * (0.3 + 0.4 * iv)
            x, y = at(u, v)
            ld = bpy.data.lights.new(f"ir_mu_strip_{iu}_{iv}", "AREA"); ld.shape = "RECTANGLE"; ld.size = 2.0; ld.size_y = 2.0; ld.energy = 520.0; ld.color = (1.0, 0.8, 0.56)
            lo = bpy.data.objects.new(f"PointLampFactory(strip).spawn_asset(mu_{iu}_{iv})", ld); bpy.context.scene.collection.objects.link(lo)
            lo.location = (x, y, 3.8)
    # exhibit / video strip walls: gilt cornice, painted frieze (the rotunda's frieze art), pilasters every 4 m; side walls v = 0 and v = S, end wall u = L
    u0 = 2 * R + 0.4; zc0, zf = 3.3, 4.5
    walls = [((u0, 0.03), (L - 0.03, 0.03)), ((u0, S - 0.03), (L - 0.03, S - 0.03)), ((L - 0.03, 0.03), (L - 0.03, S - 0.03))]
    cor, pil = [], []
    clad, base_s = [], []
    for wi, ((ua, va), (ub, vb)) in enumerate(walls):                           # travertine cladding up to the cornice + a dark base band on the exhibit/video strip walls (plain cream before)
        wl = math.hypot(ub - ua, vb - va); tu, tv = (ub - ua) / wl, (vb - va) / wl
        clad.append((W(ua, va, 0.02), W(ub, vb, 0.02), W(ub, vb, zc0), W(ua, va, zc0)))
        dv_ = ((0, 1), (0, -1), (-1, 0))[wi]; o_ = 0.015                                   # the base band stands 1.5 cm proud of the cladding
        base_s.append((W(ua + dv_[0] * o_, va + dv_[1] * o_, 0.02), W(ub + dv_[0] * o_, vb + dv_[1] * o_, 0.02), W(ub + dv_[0] * o_, vb + dv_[1] * o_, 0.7), W(ua + dv_[0] * o_, va + dv_[1] * o_, 0.7)))
    # the cladding and base band are faces of the room's own `.wall` mesh (extra material slots), NOT separate objects: separate meshes reaching the floor were counted as
    # obstacles by furnish_rooms.obstacles() and every exhibit failed placement (museum r12: 3 of 14 placed). Without a room (tests) they stay plain meshes.
    wall_o = bpy.data.objects.get(f"{room}.wall") if room else None
    base_m = fl._flat("ir_mu_base_marble", (0.11, 0.09, 0.07), 0.35)
    if wall_o is not None and wall_o.type == "MESH":
        bmw = bmesh.new(); bmw.from_mesh(wall_o.data); invw = wall_o.matrix_world.inverted(); uvw = bmw.loops.layers.uv.verify()
        for mat_, quads in ((trav, clad), (base_m, base_s)):
            if mat_.name not in [m_.name for m_ in wall_o.data.materials if m_]:
                wall_o.data.materials.append(mat_)
            idx_ = [m_.name if m_ else "" for m_ in wall_o.data.materials].index(mat_.name)
            for q in quads:
                f_ = bmw.faces.new([bmw.verts.new(invw @ Vector(p_)) for p_ in q]); f_.material_index = idx_
                for lp, c_ in zip(f_.loops, ((0, 0), (1, 0), (1, 1), (0, 1))):
                    lp[uvw].uv = c_
        bmw.to_mesh(wall_o.data); bmw.free()
    else:
        for q in clad:
            bm_ = bmesh.new(); uv_ = bm_.loops.layers.uv.verify()
            _quad(bm_, uv_, q, ((0, 0), (1, 0), (1, 1), (0, 1))); _mesh(name("StripCladding"), bm_, [trav])
        for q in base_s:
            bm_ = bmesh.new(); uv_ = bm_.loops.layers.uv.verify()
            _quad(bm_, uv_, q, ((0, 0), (1, 0), (1, 1), (0, 1))); _mesh(name("StripBase"), bm_, [base_m])
    for wi, ((ua, va), (ub, vb)) in enumerate(walls):
        cor += [("cyl", W(ua, va, zc0), W(ub, vb, zc0), 0.06, 8), ("cyl", W(ua, va, zf), W(ub, vb, zf), 0.05, 8)]
        n = max(1, int(math.hypot(ub - ua, vb - va) // 2.5))
        for k in range(n):                                               # one frieze panel per ~2.5 m
            t0, t1 = k / n, (k + 1) / n
            p0, p1 = (ua + (ub - ua) * t0, va + (vb - va) * t0), (ua + (ub - ua) * t1, va + (vb - va) * t1)
            bm = bmesh.new(); uv = bm.loops.layers.uv.verify()
            if (ART / "frieze_strip.png").exists():                          # the mural strip, one repeat per 12.5 m of wall
                wl_ = math.hypot(ub - ua, vb - va); ua_, ub_ = t0 * wl_ / 12.5, t1 * wl_ / 12.5
                _quad(bm, uv, (W(*p0, zc0 + 0.08), W(*p1, zc0 + 0.08), W(*p1, zf - 0.07), W(*p0, zf - 0.07)), ((ua_, 0), (ub_, 0), (ub_, 1), (ua_, 1)))
                _mesh(name("StripFrieze"), bm, [_img_mat("ir_mu_frieze_strip", "frieze_strip.png", 0.6)])
            else:
                _quad(bm, uv, (W(*p0, zc0 + 0.08), W(*p1, zc0 + 0.08), W(*p1, zf - 0.07), W(*p0, zf - 0.07)), ((0, 0), (1, 0), (1, 1), (0, 1)))
                _mesh(name("StripFrieze"), bm, [_img_mat(f"ir_mu_frieze_{(wi * 3 + k) % 8}", f"frieze_{(wi * 3 + k) % 8}.png", 0.6)])
        for k in range(int(math.hypot(ub - ua, vb - va) // 4) + 1):
            t = min(1.0, k * 4.0 / max(1e-6, math.hypot(ub - ua, vb - va)))
            pu, pv = ua + (ub - ua) * t, va + (vb - va) * t
            pil.append(("box", *at(pu, pv), (1.95 + zf) / 2, 0.4, 0.4, zf - 1.95))      # starts above 1.95 m: furnish_rooms.obstacles() ignores anything that high, so wall pieces still fit under them
    fl.mesh_object(name("StripCornice"), [(gilt, cor)], bevel=False)
    fl.mesh_object(name("StripPilasters"), [(trav, pil)], bevel=False)
    stats["museum_shell"] = {"R": round(R, 2), "z": round(zc_, 1), "center": [round(cu, 2), round(cv, 2)]}
