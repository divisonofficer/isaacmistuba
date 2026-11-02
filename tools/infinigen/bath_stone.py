"""Bathroom stone finish + lighting (user 10-24 on H3: 'you can feel the bathroom materials differ from the reference'; reference: greige honed large-format stone with soft veining and a satin sheen, the floor darker than the walls,
a backlit mirror and warm cove LEDs). Hooked from kit_lighting, only when ROOM_BATH_VEIN is set ("r,g,b" = the target wall colour, sRGB-linear like the other kit colours, e.g. 0.30,0.27,0.22).

  tint     every bathroom wall / floor material (rooms named bathroom_* / restroom_*) is multiplied by target / ROOM_BATH_STONE (the colour the gen stage tiled with), floors by a further ROOM_BATH_FLOOR_DARK (default 0.8)
  veins    a distorted wave (scale 0.9, distortion 14, detail 4) mapped to a +-ROOM_BATH_VEIN_AMP (default 0.07) value variation, in object coordinates: soft stone veining; per-room offset so rooms differ
  sheen    roughness remapped to 0.22-0.3 (a satin honed finish), specular level 0.5
  cove     ROOM_BATH_COVE=1: a warm (2700 K) emissive strip along the top of the walls (4 cm, 6 cm under the ceiling) with an area-light wash per room; ROOM_BATH_MIRROR_LED=1: a warm emissive plate 3 cm behind every
           bathroom mirror, 8 cm larger all round, so its outline glows
Principled inputs only. Idempotent."""
from __future__ import annotations

import os
import random

import bmesh
import bpy
from mathutils import Vector

from room_planner import proc_assets as pa


def _bb(o):
    q = [o.matrix_world @ Vector(c) for c in o.bound_box]
    return min(v.x for v in q), max(v.x for v in q), min(v.y for v in q), max(v.y for v in q), min(v.z for v in q), max(v.z for v in q)


def _tint_tree(nt, tint, amp, off):
    N, L = nt.nodes, nt.links
    b = next((n for n in N if n.type == "BSDF_PRINCIPLED"), None)
    if b is None or b.get("ir_bath_vein") or b.inputs["Transmission Weight"].default_value > 0.3 or b.inputs["Metallic"].default_value > 0.5:
        return 0
    tc = N.new("ShaderNodeTexCoord"); mp = N.new("ShaderNodeMapping"); mp.inputs["Location"].default_value = (off, off * 0.7, off * 1.3); L.new(tc.outputs["Object"], mp.inputs["Vector"])
    wv = N.new("ShaderNodeTexWave"); wv.inputs["Scale"].default_value = 0.9; wv.inputs["Distortion"].default_value = 14.0; wv.inputs["Detail"].default_value = 4.0; L.new(mp.outputs["Vector"], wv.inputs["Vector"])
    mr = N.new("ShaderNodeMapRange"); mr.inputs["To Min"].default_value = 1.0 - amp; mr.inputs["To Max"].default_value = 1.0 + amp; L.new(wv.outputs["Fac"], mr.inputs["Value"])
    m1 = N.new("ShaderNodeMix"); m1.data_type = "RGBA"; m1.blend_type = "MULTIPLY"; m1.inputs["Factor"].default_value = 1.0; m1.inputs[7].default_value = tuple(tint) + (1.0,)
    if b.inputs["Base Color"].is_linked:
        L.new(b.inputs["Base Color"].links[0].from_socket, m1.inputs[6])
    else:
        m1.inputs[6].default_value = b.inputs["Base Color"].default_value
    m2 = N.new("ShaderNodeMix"); m2.data_type = "RGBA"; m2.blend_type = "MULTIPLY"; m2.inputs["Factor"].default_value = 1.0
    L.new(m1.outputs[2], m2.inputs[6]); vv = N.new("ShaderNodeCombineColor"); L.new(mr.outputs["Result"], vv.inputs[0]); L.new(mr.outputs["Result"], vv.inputs[1]); L.new(mr.outputs["Result"], vv.inputs[2]); L.new(vv.outputs[0], m2.inputs[7])
    L.new(m2.outputs[2], b.inputs["Base Color"])
    rr = N.new("ShaderNodeMapRange"); rr.inputs["To Min"].default_value = 0.22; rr.inputs["To Max"].default_value = 0.30; L.new(wv.outputs["Fac"], rr.inputs["Value"])
    if b.inputs["Roughness"].is_linked:                                   # the ceramic's own roughness term: clamp it into the satin band after it
        mx = N.new("ShaderNodeMapRange"); mx.inputs["To Min"].default_value = 0.22; mx.inputs["To Max"].default_value = 0.3; L.new(b.inputs["Roughness"].links[0].from_socket, mx.inputs["Value"]); L.new(mx.outputs["Result"], b.inputs["Roughness"])
    else:
        L.new(rr.outputs["Result"], b.inputs["Roughness"])
    for nm in ("Specular IOR Level", "Specular"):
        if nm in b.inputs:
            b.inputs[nm].default_value = 0.5; break
    b["ir_bath_vein"] = True; b["weathered"] = True
    return 1


def _tint_mat(m, tint, amp, off):
    if m is None or not m.use_nodes or m.get("ir_bath_vein"):
        return 0
    n = _tint_tree(m.node_tree, tint, amp, off)
    for g in [x for x in m.node_tree.nodes if x.type == "GROUP" and x.node_tree]:
        if any(y.type == "BSDF_PRINCIPLED" for y in g.node_tree.nodes):
            if g.node_tree.users > 1 or not g.node_tree.get("ir_bath_copy"):
                g.node_tree = g.node_tree.copy(); g.node_tree["ir_bath_copy"] = True                      # a private copy: the ceramic groups are shared between the wall and the floor
            n += _tint_tree(g.node_tree, tint, amp, off)
    if n:
        m["ir_bath_vein"] = True; m["weathered"] = True
    return 1 if n else 0


def apply(stats):
    raw = os.environ.get("ROOM_BATH_VEIN")
    if not raw:
        return 0
    tgt = [float(v) for v in raw.split(",")]; src = [float(v) for v in (os.environ.get("ROOM_BATH_STONE") or "0.82,0.76,0.66").split(",")]
    tint = [min(3.0, t / max(s, 1e-3)) for t, s in zip(tgt, src)]; dark = float(os.environ.get("ROOM_BATH_FLOOR_DARK") or 0.8); amp = float(os.environ.get("ROOM_BATH_VEIN_AMP") or 0.07)
    n = 0; rooms = []
    for o in bpy.data.objects:
        if o.type != "MESH" or not o.name.startswith(("bathroom_", "restroom_")) or not o.name.endswith((".wall", ".floor")):
            continue
        rooms.append(o.name.rsplit(".", 1)[0]); off = random.Random(o.name.rsplit(".", 1)[0]).uniform(0, 40)
        t = [c * dark for c in tint] if o.name.endswith(".floor") else tint
        for sl in o.material_slots:
            if sl.material is not None and not sl.material.get("ir_bath_vein"):
                if o.name.endswith(".floor") or True:
                    key = (sl.material.name, off, tuple(t))
                n += _tint_mat(sl.material, t, amp, off)
    for o in [o for o in bpy.data.objects if o.name.startswith(("BathCove(", "BathMirrorLed("))]:
        bpy.data.objects.remove(o, do_unlink=True)
    warm = pa._flat("ir_bath_led", (1.0, 0.7, 0.4), 0.4); b = warm.node_tree.nodes["Principled BSDF"]; b.inputs["Emission Color"].default_value = (1.0, 0.7, 0.4, 1); b.inputs["Emission Strength"].default_value = 6.0
    nc = nm = 0
    for rn in sorted(set(rooms)):
        w = bpy.data.objects.get(rn + ".wall")
        if w is None:
            continue
        x0, x1, y0, y1, z0, z1 = _bb(w)
        if os.environ.get("ROOM_BATH_COVE") == "1":
            bm = bmesh.new(); zz = z1 - 0.06
            for (cx, cy, sx, sy) in (((x0 + x1) / 2, y0 + 0.04, x1 - x0 - 0.1, 0.04), ((x0 + x1) / 2, y1 - 0.04, x1 - x0 - 0.1, 0.04), (x0 + 0.04, (y0 + y1) / 2, 0.04, y1 - y0 - 0.1), (x1 - 0.04, (y0 + y1) / 2, 0.04, y1 - y0 - 0.1)):
                r = bmesh.ops.create_cube(bm, size=1.0); bmesh.ops.scale(bm, vec=(sx, sy, 0.04), verts=r["verts"]); bmesh.ops.translate(bm, vec=(cx, cy, zz), verts=r["verts"])
            me = bpy.data.meshes.new("BathCove"); bm.to_mesh(me); bm.free(); me.materials.append(warm)
            ob = bpy.data.objects.new(f"BathCove({rn})", me); bpy.context.scene.collection.objects.link(ob)
            ld = bpy.data.lights.new(f"ir_bath_cove_{rn}", "AREA"); ld.shape = "RECTANGLE"; ld.size = max(x1 - x0, 0.5) * 0.8; ld.size_y = max(y1 - y0, 0.5) * 0.8; ld.energy = 25.0; ld.color = (1.0, 0.72, 0.45)
            lo = bpy.data.objects.new(f"PointLampFactory(bathcove).spawn_asset({rn})", ld); bpy.context.scene.collection.objects.link(lo); lo.location = ((x0 + x1) / 2, (y0 + y1) / 2, z1 - 0.1); lo.rotation_euler = (3.14159, 0, 0); nc += 1
        if os.environ.get("ROOM_BATH_MIRROR_LED") == "1":
            for mo in [o for o in bpy.data.objects if o.type == "MESH" and o.parent is None and o.name.startswith("MirrorFactory")]:
                a0, a1, b0, b1, c0, c1 = _bb(mo)
                if not (x0 - 0.2 < (a0 + a1) / 2 < x1 + 0.2 and y0 - 0.2 < (b0 + b1) / 2 < y1 + 0.2):
                    continue
                thin_x = (a1 - a0) < (b1 - b0)
                bm = bmesh.new(); r = bmesh.ops.create_cube(bm, size=1.0)
                bmesh.ops.scale(bm, vec=((0.01 if thin_x else a1 - a0 + 0.16), (b1 - b0 + 0.16) if thin_x else 0.01, c1 - c0 + 0.16), verts=r["verts"])
                bmesh.ops.translate(bm, vec=((a0 + a1) / 2 + (-0.03 if thin_x else 0), (b0 + b1) / 2 + (0 if thin_x else -0.03), (c0 + c1) / 2), verts=r["verts"])
                me = bpy.data.meshes.new("BathMirrorLed"); bm.to_mesh(me); bm.free(); me.materials.append(warm)
                bpy.context.scene.collection.objects.link(bpy.data.objects.new(f"BathMirrorLed({rn})", me)); nm += 1
    stats["bath_stone"] = {"materials": n, "coves": nc, "mirror_leds": nm, "tint": [round(t, 2) for t in tint]}
    return n
