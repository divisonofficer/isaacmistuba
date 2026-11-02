"""Clear window glass for the camera (S35 r14 B1 / O4 r4 F4: window glazing rendered as an opaque white panel, no street behind it). Hooked from kit_lighting, only when ROOM_CLEAR_GLASS=1.

The Principled transmission of ir_bg_glass / ir_env_win_glass on a single quad blew out to white in Cycles (S35: window region 244/255 with the pane, 124 with the pane hidden or swapped for a Transparent BSDF).
Here the surface becomes Transparent (the glass tint) mixed with 4 % of a glossy white layer, so the street card reads through the glass with a faint reflection; shadow rays stay transparent. Idempotent (material flag)."""
from __future__ import annotations

import os

import bpy
from mathutils import Vector

NAMES = ("ir_bg_glass", "ir_env_win_glass", "ir_gp_glass", "ir_gp_leaf_glass", "ir_shut_door_glass_pane", "ir_shower_glass")      # + the glass partitions and their door leaves (N2: a dark glazed door read as a shut slab)
FROST = "ir_frosted_glass"     # architecture_pass: service-room windows (restroom, closet) get this slab-like frost (+ a roller blind); with ROOM_FROST_LOWER=1 they become clear above a frosted lower half (O4 r5)


def apply(stats):
    n = 0
    for m in bpy.data.materials:
        if (m.name not in NAMES and not (m.name == FROST and os.environ.get("ROOM_FROST_LOWER") == "1")) or not m.use_nodes or m.get("ir_clear"):
            continue
        nt = m.node_tree; N, L = nt.nodes, nt.links
        out = next((x for x in N if x.type == "OUTPUT_MATERIAL"), None); b = next((x for x in N if x.type == "BSDF_PRINCIPLED"), None)
        if out is None or b is None:
            continue
        tint = tuple(b.inputs["Base Color"].default_value)
        tr = N.new("ShaderNodeBsdfTransparent"); tr.inputs["Color"].default_value = tint
        gl = N.new("ShaderNodeBsdfGlossy"); gl.inputs["Roughness"].default_value = 0.03; gl.inputs["Color"].default_value = (1, 1, 1, 1)
        mx = N.new("ShaderNodeMixShader"); mx.inputs["Fac"].default_value = 0.04
        L.new(tr.outputs["BSDF"], mx.inputs[1]); L.new(gl.outputs["BSDF"], mx.inputs[2])
        lp = N.new("ShaderNodeLightPath"); sh = N.new("ShaderNodeMixShader"); t2 = N.new("ShaderNodeBsdfTransparent")
        L.new(lp.outputs["Is Shadow Ray"], sh.inputs["Fac"]); L.new(mx.outputs["Shader"], sh.inputs[1]); L.new(t2.outputs["BSDF"], sh.inputs[2])
        L.new(sh.outputs["Shader"], out.inputs["Surface"])
        m["ir_clear"] = True; n += 1
    if os.environ.get("ROOM_FROST_LOWER") == "1":
        stats["frost_lower"] = _frost_lower()
    if os.environ.get("ROOM_THIN_FRAMES") == "1":
        thin_frames(stats)
    stats["clear_glass"] = n
    return n


def _frost_lower():
    """A frosted band over the lower 45 % of every window whose glass slot is ir_frosted_glass (idempotent: previous bands are removed first)."""
    for o in [o for o in bpy.data.objects if o.name.startswith("WindowFrostBand(")]:
        bpy.data.objects.remove(o, do_unlink=True)
    fm = bpy.data.materials.get("ir_win_frost_band")
    if fm is None:
        fm = bpy.data.materials.new("ir_win_frost_band"); fm.use_nodes = True; b = fm.node_tree.nodes["Principled BSDF"]
        b.inputs["Base Color"].default_value = (0.9, 0.93, 0.95, 1); b.inputs["Roughness"].default_value = 0.7; b.inputs["Emission Color"].default_value = (0.85, 0.92, 1.0, 1); b.inputs["Emission Strength"].default_value = 0.6
    n = 0
    for o in list(bpy.data.objects):
        if o.type != "MESH" or "Window" not in o.name.split("(")[0] or not any(sl.material and sl.material.name == FROST for sl in o.material_slots):
            continue
        pts = [o.matrix_world @ Vector(c) for c in o.bound_box]
        x0, x1 = min(q.x for q in pts), max(q.x for q in pts); y0, y1 = min(q.y for q in pts), max(q.y for q in pts); z0, z1 = min(q.z for q in pts), max(q.z for q in pts)
        h = (z1 - z0) * 0.45
        me = bpy.data.meshes.new("WindowFrostBand"); import bmesh
        bm = bmesh.new(); r = bmesh.ops.create_cube(bm, size=1.0)
        sx, sy = (max(x1 - x0, 0.02) + 0.02, max(y1 - y0, 0.02) + 0.02)
        thin_x = (x1 - x0) < (y1 - y0)
        bmesh.ops.scale(bm, vec=((0.03 if thin_x else sx), (sy if thin_x else 0.03), h), verts=r["verts"]); bmesh.ops.translate(bm, vec=((x0 + x1) / 2, (y0 + y1) / 2, z0 + h / 2 + 0.02), verts=r["verts"])
        bm.to_mesh(me); bm.free(); me.materials.append(fm)
        bo = bpy.data.objects.new(f"WindowFrostBand({o.name})", me); bpy.context.scene.collection.objects.link(bo); n += 1
    return n


def thin_frames(stats):
    """ROOM_THIN_FRAMES=1 (O2 r23: 'thick unbevelled white boxes protrude past the glass partitions'): a door whose leaf is the partition glass (ir_gp_leaf_glass / ir_shut_door_glass) gets a thin brushed-steel casing: the casing's
    thickness (local y, the wall depth) is scaled to 7 cm, its material becomes a brushed steel Principled (metallic 1, roughness 0.3, a fine streak), so the frame is flush with the glass. Idempotent."""
    m = bpy.data.materials.get("ir_thin_frame_steel")
    if m is None:
        m = bpy.data.materials.new("ir_thin_frame_steel"); m.use_nodes = True; N, L = m.node_tree.nodes, m.node_tree.links; b = N["Principled BSDF"]
        b.inputs["Base Color"].default_value = (0.7, 0.71, 0.73, 1); b.inputs["Metallic"].default_value = 1.0
        tc = N.new("ShaderNodeTexCoord"); mp = N.new("ShaderNodeMapping"); mp.inputs["Scale"].default_value = (4.0, 300.0, 4.0); L.new(tc.outputs["Object"], mp.inputs["Vector"])
        nz = N.new("ShaderNodeTexNoise"); nz.inputs["Scale"].default_value = 1.0; L.new(mp.outputs["Vector"], nz.inputs["Vector"])
        rg = N.new("ShaderNodeMapRange"); rg.inputs["To Min"].default_value = 0.24; rg.inputs["To Max"].default_value = 0.4; L.new(nz.outputs["Fac"], rg.inputs["Value"]); L.new(rg.outputs["Result"], b.inputs["Roughness"])
        m["weathered"] = True; b["weathered"] = True
    n = 0
    for o in bpy.data.objects:
        if o.type != "MESH" or not o.name.startswith("DoorCasingFactory") or o.parent is None or o.get("ir_thin"):
            continue
        if not any(c.type == "MESH" and any(sl.material and sl.material.name in ("ir_gp_leaf_glass", "ir_shut_door_glass") for sl in c.material_slots) for c in o.parent.children):
            continue
        o.scale = (o.scale[0], o.scale[1] * min(1.0, 0.07 / max(o.dimensions[1] / max(o.scale[1], 1e-6), 1e-3)), o.scale[2])
        o.data = o.data.copy(); o.data.materials.clear(); o.data.materials.append(m); o["ir_thin"] = 1; n += 1
    stats["thin_frames"] = n
    return n
