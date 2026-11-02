"""White square wall tile for chosen room types (floors G / H restroom refs: 'white tiles', ours came out Infinigen's green).

Late pass (kit_lighting, after the floor tile pass; ROOM_WALL_TILE_ROOMS=restroom,bathroom = room-name prefixes). Every material of those rooms' `.wall` object is replaced by a copy whose base colour is a
baked tile image (tile_floor._bake, a 0.2 m square tile by default, light grout) sampled triplanar in world metres: (y, z) on walls facing +-x, (x, z) on walls facing +-y.
Env: ROOM_WALL_TILE=r,g,b (default 0.93,0.93,0.91)  ROOM_WALL_TILE_SIZE=0.2  ROOM_TILE_GROUT=0.003  ROOM_TILE_VARY (default 0.03)  ROOM_TILE_ROUGH (default 0.3). Stats: stats["tile_walls"] = slots changed.
"""
from __future__ import annotations

import os

import bpy

import tile_floor as tf


def _material(name, img, size_m, rough):
    m = bpy.data.materials.get(name)
    if m is not None:
        return m
    m = bpy.data.materials.new(name); m.use_nodes = True
    N, Lk = m.node_tree.nodes, m.node_tree.links; N.clear()
    out = N.new("ShaderNodeOutputMaterial"); b = N.new("ShaderNodeBsdfPrincipled"); Lk.new(b.outputs["BSDF"], out.inputs["Surface"])
    geo = N.new("ShaderNodeNewGeometry"); sp = N.new("ShaderNodeSeparateXYZ"); sn = N.new("ShaderNodeSeparateXYZ")
    Lk.new(geo.outputs["Position"], sp.inputs[0]); Lk.new(geo.outputs["Normal"], sn.inputs[0])
    ax = N.new("ShaderNodeMath"); ax.operation = "ABSOLUTE"; ay = N.new("ShaderNodeMath"); ay.operation = "ABSOLUTE"
    Lk.new(sn.outputs["X"], ax.inputs[0]); Lk.new(sn.outputs["Y"], ay.inputs[0])
    gt = N.new("ShaderNodeMath"); gt.operation = "GREATER_THAN"; Lk.new(ax.outputs[0], gt.inputs[0]); Lk.new(ay.outputs[0], gt.inputs[1])      # 1 on walls facing +-x
    d = N.new("ShaderNodeMath"); d.operation = "SUBTRACT"; Lk.new(sp.outputs["Y"], d.inputs[0]); Lk.new(sp.outputs["X"], d.inputs[1])
    mu = N.new("ShaderNodeMath"); mu.operation = "MULTIPLY"; Lk.new(d.outputs[0], mu.inputs[0]); Lk.new(gt.outputs[0], mu.inputs[1])
    u = N.new("ShaderNodeMath"); u.operation = "ADD"; Lk.new(sp.outputs["X"], u.inputs[0]); Lk.new(mu.outputs[0], u.inputs[1])              # x + (y - x) * c
    cx = N.new("ShaderNodeCombineXYZ"); Lk.new(u.outputs[0], cx.inputs["X"]); Lk.new(sp.outputs["Z"], cx.inputs["Y"])
    mp = N.new("ShaderNodeMapping"); mp.inputs["Scale"].default_value = (1.0 / size_m, 1.0 / size_m, 1.0); Lk.new(cx.outputs[0], mp.inputs["Vector"])
    tx = N.new("ShaderNodeTexImage"); tx.image = img; tx.interpolation = "Smart"; tx.extension = "REPEAT"
    Lk.new(mp.outputs["Vector"], tx.inputs["Vector"]); Lk.new(tx.outputs["Color"], b.inputs["Base Color"]); b.inputs["Roughness"].default_value = rough
    return m


def apply(stats):
    rooms = tuple(x.strip() for x in (os.environ.get("ROOM_WALL_TILE_ROOMS") or "").split(",") if x.strip())
    if not rooms:
        return 0
    base = tuple(float(v) for v in (os.environ.get("ROOM_WALL_TILE") or "0.93,0.93,0.91").split(","))
    tile = float(os.environ.get("ROOM_WALL_TILE_SIZE") or 0.2); grout = float(os.environ.get("ROOM_TILE_GROUT") or 0.003)
    vary = float(os.environ.get("ROOM_TILE_VARY") or 0.03); rough = float(os.environ.get("ROOM_TILE_ROUGH") or 0.3)
    png, size_m = tf._bake(base, tile, grout, vary)
    img = bpy.data.images.load(str(png), check_existing=True); img.colorspace_settings.name = "sRGB"
    mat = _material(f"ir_wall_tile_{png.stem}", img, size_m, rough)
    cnt = 0
    for o in bpy.data.objects:
        if o.type != "MESH" or not o.name.endswith(".wall") or not o.name.startswith(rooms):
            continue
        for sl in o.material_slots:
            sl.material = mat; cnt += 1
    stats["tile_walls"] = cnt
    return cnt
