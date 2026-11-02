"""Usage realism (user review 10-23, axis C): imperfect alignment, variation inside repeats. Hooked from kit_lighting after mfg_detail, only when ROOM_USAGE_REAL=1:

    import usage_realism; stats["usage_realism"] = usage_realism.apply(stats)

  chairs   every chair / stool is turned +-(3..8) deg and slid +-3 cm (ROOM_USAGE_YAW = max deg, default 8; ROOM_USAGE_SLIDE = max m, default 0.03; 0 turns that part off). Seeded by the object name.
  pulled   ROOM_USAGE_PULLED=n: n stools (nearest a CafeCounter) are pulled out 12-20 cm from it (default 0 = off)
  repeats  every material used by >= 3 objects gets a per-object colour jitter (+-4 % value, +-0.03 roughness) from Object Info > Random, so repeated units (stools, bowls, bottles, chairs) no longer match exactly.
           The jitter lives in the shader: albedo / roughness GT channels carry it. Glass, emissive, alpha, screen / card materials are left alone.
"""
from __future__ import annotations

import math
import os
import random

import bpy

CHAIR = ("chair", "stool", "armchair", "pouf")


def _chairs(yaw_max, slide):
    n = 0
    for o in bpy.data.objects:
        if o.type != "MESH" or o.parent is not None or not any(k in o.name.lower() for k in CHAIR) or o.get("ir_usage"):
            continue
        r = random.Random(o.name)
        if yaw_max > 0:
            o.rotation_euler[2] += math.radians(r.uniform(3, yaw_max) * r.choice((-1, 1)))
        if slide > 0:
            o.location.x += r.uniform(-slide, slide); o.location.y += r.uniform(-slide, slide)
        o["ir_usage"] = 1; n += 1
    return n


def _pulled(n):
    """R4: n stools are pulled out 12-20 cm from the counter they stand at (seeded by the stool name)."""
    from mathutils import Vector
    cts = []
    for o in bpy.data.objects:
        if o.type == "MESH" and o.name.startswith("CafeCounterFactory"):
            pts = [o.matrix_world @ Vector(c) for c in o.bound_box]
            cts.append((min(p.x for p in pts), max(p.x for p in pts), min(p.y for p in pts), max(p.y for p in pts)))
    stools = sorted((o for o in bpy.data.objects if o.type == "MESH" and o.parent is None and "stool" in o.name.lower()), key=lambda o: o.name)
    if not cts or not stools or n <= 0:
        return 0
    rnd = random.Random("pulled:" + stools[0].name); moved = 0
    for o in rnd.sample(stools, min(n, len(stools))):
        p = o.matrix_world.translation
        best = None
        for x0, x1, y0, y1 in cts:
            q = Vector((min(max(p.x, x0), x1), min(max(p.y, y0), y1), p.z)); d = (p - q).length
            if best is None or d < best[0]:
                best = (d, p - q)
        if best is None or best[0] > 1.2 or best[1].length < 1e-4:
            continue
        v = Vector((best[1].x, best[1].y, 0)).normalized() * rnd.uniform(0.12, 0.2)
        o.location.x += v.x; o.location.y += v.y; moved += 1
    return moved


def _repeats(amp):
    import surface_realism as sr
    cnt = {}
    for o in bpy.data.objects:
        if o.type == "MESH":
            for ms in {s.material for s in o.material_slots if s.material is not None}:
                cnt[ms] = cnt.get(ms, 0) + 1
    n = 0
    for m, k in cnt.items():
        if k < 3 or not m.use_nodes or m.get("ir_usage_jit"):
            continue
        nt = m.node_tree; b = next((x for x in nt.nodes if x.type == "BSDF_PRINCIPLED"), None)
        if b is None or sr._skip(m, b, ignore_done=True):
            continue
        N, L = nt.nodes, nt.links
        oi = N.new("ShaderNodeObjectInfo")
        v = N.new("ShaderNodeMath"); v.operation = "MULTIPLY_ADD"; L.new(oi.outputs["Random"], v.inputs[0]); v.inputs[1].default_value = 0.08 * amp; v.inputs[2].default_value = 1.0 - 0.04 * amp      # 0.96 .. 1.04
        cv = N.new("ShaderNodeCombineColor"); [L.new(v.outputs[0], cv.inputs[q]) for q in range(3)]
        bc = b.inputs["Base Color"]; mix = N.new("ShaderNodeMix"); mix.data_type = "RGBA"; mix.blend_type = "MULTIPLY"; mix.inputs["Factor"].default_value = 1.0
        if bc.links:
            src = bc.links[0].from_socket
            for l in list(bc.links):
                L.remove(l)
            L.new(src, mix.inputs["A"])
        else:
            mix.inputs["A"].default_value = bc.default_value
        L.new(cv.outputs["Color"], mix.inputs["B"]); L.new(mix.outputs["Result"], bc)
        rn = b.inputs["Roughness"]; rj = N.new("ShaderNodeMath"); rj.operation = "MULTIPLY_ADD"; L.new(oi.outputs["Random"], rj.inputs[0]); rj.inputs[1].default_value = 0.06 * amp; rj.inputs[2].default_value = -0.03 * amp
        ad = N.new("ShaderNodeMath"); ad.operation = "ADD"
        if rn.links:
            src = rn.links[0].from_socket
            for l in list(rn.links):
                L.remove(l)
            L.new(src, ad.inputs[0])
        else:
            ad.inputs[0].default_value = rn.default_value
        L.new(rj.outputs[0], ad.inputs[1]); cl = N.new("ShaderNodeClamp"); cl.inputs["Min"].default_value = 0.03; L.new(ad.outputs[0], cl.inputs["Value"]); L.new(cl.outputs["Result"], rn)
        m["ir_usage_jit"] = 1; n += 1
    return n


def apply(stats):
    if os.environ.get("ROOM_USAGE_REAL") != "1":
        return {}
    amp = float(os.environ.get("ROOM_REAL_AMP") or 1.0)
    return {"chairs": _chairs(float(os.environ.get("ROOM_USAGE_YAW") or 8.0), float(os.environ.get("ROOM_USAGE_SLIDE") or 0.03)), "pulled_stools": _pulled(int(os.environ.get("ROOM_USAGE_PULLED") or 0)), "repeat_materials": _repeats(amp)}
