"""600x600 perforated metal tile ceiling (O2 hallway ref). ROOM_PERF_CEILING=<ceiling-name prefixes, comma list, e.g. hallway>.
Removes the suspended grid / linear LEDs / exposed-service objects under the matching ceilings, paints the ceiling with a perforated-metal shader (tile reveals + hole grid, world-space), and adds
flush emissive 0.6 m panels (+ area light) every ~2.4 m along the long axis. Idempotent via scene["ir_perf_ceiling"]."""
import os

import bpy
from mathutils import Vector

from lab_ceiling import REMOVE, _obj, _emit
from room_planner import proc_assets as pa


def _mat():
    m = bpy.data.materials.get("ir_perf_ceiling")
    if m is not None:
        return m
    m = pa._flat("ir_perf_ceiling", (0.66, 0.68, 0.70), 0.35, 1.0); m["weathered"] = True
    nt = m.node_tree; N, L = nt.nodes, nt.links; b = N["Principled BSDF"]
    tc = N.new("ShaderNodeTexCoord"); sp = N.new("ShaderNodeSeparateXYZ"); L.new(tc.outputs["Object"], sp.inputs["Vector"])
    def mth(op, a, b_=None, v=None):
        n = N.new("ShaderNodeMath"); n.operation = op
        for i, s in enumerate((a, b_)):
            if s is None:
                continue
            if isinstance(s, (int, float)):
                n.inputs[i].default_value = s
            else:
                L.new(s, n.inputs[i])
        return n.outputs[0]
    P = 40.0                                                        # hole pitch 25 mm
    u = mth("FRACT", mth("MULTIPLY", sp.outputs["X"], P)); v = mth("FRACT", mth("MULTIPLY", sp.outputs["Y"], P))
    du = mth("SUBTRACT", u, 0.5); dv = mth("SUBTRACT", v, 0.5)
    d = mth("SQRT", mth("ADD", mth("MULTIPLY", du, du), mth("MULTIPLY", dv, dv)))
    hole = mth("LESS_THAN", d, 0.3)
    def reveal(c):
        f = mth("FRACT", mth("DIVIDE", c, 0.6)); return mth("LESS_THAN", mth("MINIMUM", f, mth("SUBTRACT", 1.0, f)), 0.006)   # 3.6 mm dark joint each side
    line = mth("MAXIMUM", reveal(sp.outputs["X"]), reveal(sp.outputs["Y"]))
    dark = mth("MAXIMUM", hole, line)
    mix = N.new("ShaderNodeMix"); mix.data_type = "RGBA"
    mix.inputs["A"].default_value = (0.66, 0.68, 0.70, 1); mix.inputs["B"].default_value = (0.06, 0.06, 0.065, 1)
    L.new(dark, mix.inputs["Factor"]); L.new(mix.outputs["Result"], b.inputs["Base Color"])
    return m


def apply(stats):
    only = tuple(x.strip() for x in (os.environ.get("ROOM_PERF_CEILING") or "").split(",") if x.strip())
    sc = bpy.context.scene
    if not only or sc.get("ir_perf_ceiling"):
        return 0
    mat = _mat(); panel = _emit("ir_perf_panel", (1.0, 0.95, 0.85), 25.0); n = 0
    for c in [o for o in bpy.data.objects if o.type == "MESH" and o.name.endswith(".ceiling") and o.name.startswith(only)]:
        pts = [c.matrix_world @ Vector(v) for v in c.bound_box]
        x0, x1, y0, y1, zc = min(p.x for p in pts), max(p.x for p in pts), min(p.y for p in pts), max(p.y for p in pts), min(p.z for p in pts)
        for o in list(bpy.data.objects):
            nm = o.name.split("(")[0]
            if o.type == "MESH" and (nm in REMOVE or nm.startswith("Exposed")) and x0 - 0.2 < o.matrix_world.translation.x < x1 + 0.2 \
                    and y0 - 0.2 < o.matrix_world.translation.y < y1 + 0.2 and max((o.matrix_world @ Vector(v)).z for v in o.bound_box) > 2.2:
                bpy.data.objects.remove(o, do_unlink=True)
        for sl in c.material_slots:
            sl.material = mat
        alx = (x1 - x0) >= (y1 - y0); L, Wd = ((x1 - x0), (y1 - y0)) if alx else ((y1 - y0), (x1 - x0))
        k = max(1, int(L // 2.4)); prims, pos = [], []
        for i in range(k):
            u = L * (i + 0.5) / k; xy = (x0 + u, (y0 + y1) / 2) if alx else ((x0 + x1) / 2, y0 + u)
            prims.append(("box", (xy[0], xy[1], zc - 0.01), (0.6, 0.6, 0.02))); pos.append(xy)
        _obj(f"PerfPanels({c.name})", [(panel, prims)])
        for i, xy in enumerate(pos):
            ld = bpy.data.lights.new(f"ir_perf_light_{c.name}_{i}", "AREA"); ld.shape = "SQUARE"; ld.size = 0.6; ld.energy = 60; ld.color = (1.0, 0.95, 0.85)
            o = bpy.data.objects.new(ld.name, ld); o.location = (xy[0], xy[1], zc - 0.05); o.rotation_euler = (3.14159, 0, 0); bpy.context.scene.collection.objects.link(o)
        n += 1
    sc["ir_perf_ceiling"] = 1; stats["perf_ceiling"] = n
    return n
