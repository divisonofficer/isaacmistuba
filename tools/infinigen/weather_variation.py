"""Per-object variation on top of weather_pass (user 2026-10-17 'texture flat'; arm 5 of the cafeP A/B).

weather_pass puts its patches, streaks and grain in OBJECT space, but every object that shares a material (16 identical cafe chairs, a row
of table tops) gets the same pattern at the same place, so identical objects read as one stamped copy. This pass runs AFTER weather_pass
(kit_lighting) on the finished scene and adds, per Principled BSDF that weather_pass touched:
  * offset   -- every noise / mapping node fed by Texture Coordinate > Object gets a per-object offset from Object Info > Random, so the
                patches, streaks and scan tiles land differently on each object
  * tint     -- base colour x (1 +- 0.06 * amount) and roughness +- 0.06 * amount per object
  * edge     -- on tops / fronts / wood (name hints): convex edges (Bevel node normal vs true normal) lighten the colour and drop the roughness,
                like worn paint or polished wood
Default OFF: nothing calls this unless a pipeline runs it (IR_WEATHER_VARIATION=1 in kit_lighting would be the hook).

    python weather_variation.py IN.blend --out OUT.blend [--amount 1.0] [--edge 0.35]
    from weather_variation import vary_materials; vary_materials(1.0, 0.35)       # inside another bpy session
"""
import sys

import bpy

EDGE_HINTS = ("top", "counter", "table", "desk", "cabinet", "locker", "shelf", "wood", "laminate", "front", "chair", "banquette", "frame")
SKIP_NAMES = ("glass", "window", "lamp", "light", "emit", "emission", "screen", "mirror", "sky", "water", "led")


def _math(nt, op, a, b=None, clamp=False):
    n = nt.nodes.new("ShaderNodeMath"); n.operation = op; n.use_clamp = clamp
    for k, x in enumerate((a, b)):
        if x is None:
            continue
        if hasattr(x, "node"):
            nt.links.new(x, n.inputs[k])
        else:
            n.inputs[k].default_value = x
    return n.outputs[0]


def _vary_tree(nt, name, amount, edge):
    """Returns how many Principled nodes were varied in this node tree."""
    principled = [b for b in nt.nodes if b.type == "BSDF_PRINCIPLED" and b.get("weathered") and not b.get("varied")]
    if not principled or any(k in name.lower() for k in SKIP_NAMES):
        return 0
    L = nt.links
    oi = nt.nodes.new("ShaderNodeObjectInfo")
    rnd = oi.outputs["Random"]
    # (1) a per-object offset on every object-space noise / mapping node
    off = nt.nodes.new("ShaderNodeCombineXYZ")
    for i, k in enumerate((41.0, 67.0, 89.0)):
        L.new(_math(nt, "MULTIPLY", rnd, k), off.inputs[i])
    for n in [x for x in nt.nodes if x.type in ("TEX_NOISE", "MAPPING") and x.inputs["Vector"].is_linked]:
        src = n.inputs["Vector"].links[0].from_socket
        if src.node.type == "TEX_COORD" and src.name == "Object":
            add = nt.nodes.new("ShaderNodeVectorMath"); add.operation = "ADD"
            L.new(src, add.inputs[0]); L.new(off.outputs[0], add.inputs[1]); L.new(add.outputs[0], n.inputs["Vector"])
    for b in principled:
        # (2) per-object tint of the colour and a roughness nudge
        t = _math(nt, "ADD", 1.0, _math(nt, "MULTIPLY", _math(nt, "SUBTRACT", rnd, 0.5), 0.12 * amount))
        tint = nt.nodes.new("ShaderNodeCombineColor")
        for i in range(3):
            L.new(t, tint.inputs[i])
        mix = nt.nodes.new("ShaderNodeMix"); mix.data_type = "RGBA"; mix.blend_type = "MULTIPLY"; mix.inputs["Factor"].default_value = 1.0
        if b.inputs["Base Color"].is_linked:
            L.new(b.inputs["Base Color"].links[0].from_socket, mix.inputs[6])
        else:
            mix.inputs[6].default_value = b.inputs["Base Color"].default_value
        L.new(tint.outputs["Color"], mix.inputs[7])
        col = mix.outputs[2]
        r0 = b.inputs["Roughness"].links[0].from_socket if b.inputs["Roughness"].is_linked else None
        r_in = r0 if r0 is not None else _math(nt, "ADD", b.inputs["Roughness"].default_value, 0.0)
        rough = _math(nt, "ADD", r_in, _math(nt, "MULTIPLY", _math(nt, "SUBTRACT", rnd, 0.5), 0.12 * amount))
        # (3) edge wear on tops / fronts / wood
        if edge > 0 and any(k in name.lower() for k in EDGE_HINTS):
            bev = nt.nodes.new("ShaderNodeBevel"); bev.inputs["Radius"].default_value = 0.004; bev.samples = 6
            geo = nt.nodes.new("ShaderNodeNewGeometry")
            dot = nt.nodes.new("ShaderNodeVectorMath"); dot.operation = "DOT_PRODUCT"
            L.new(bev.outputs["Normal"], dot.inputs[0]); L.new(geo.outputs["Normal"], dot.inputs[1])
            m = nt.nodes.new("ShaderNodeMapRange"); m.inputs["From Min"].default_value = 1.0; m.inputs["From Max"].default_value = 0.75
            L.new(dot.outputs["Value"], m.inputs["Value"])
            w = _math(nt, "MULTIPLY", m.outputs["Result"], edge * amount, clamp=True)
            wc = nt.nodes.new("ShaderNodeMix"); wc.data_type = "RGBA"; wc.blend_type = "MIX"
            L.new(w, wc.inputs["Factor"]); L.new(col, wc.inputs[6]); wc.inputs[7].default_value = (0.78, 0.72, 0.62, 1.0)
            col = wc.outputs[2]
            rough = _math(nt, "SUBTRACT", rough, _math(nt, "MULTIPLY", w, 0.25), clamp=True)
        L.new(col, b.inputs["Base Color"]); L.new(_math(nt, "ADD", rough, 0.0, clamp=True), b.inputs["Roughness"])
        b["varied"] = True
    return len(principled)


def vary_materials(amount=1.0, edge=0.35):
    n = 0
    for m in list(bpy.data.materials):
        if m.use_nodes and m.users and not m.library:
            n += _vary_tree(m.node_tree, m.name, amount, edge)
    print(f"VARIED {n} Principled nodes ({len(bpy.data.materials)} materials)", flush=True)
    return n


if __name__ == "__main__":
    a = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    out = a[a.index("--out") + 1]
    amt = float(a[a.index("--amount") + 1]) if "--amount" in a else 1.0
    edge = float(a[a.index("--edge") + 1]) if "--edge" in a else 0.35
    src = next((x for x in a if x.endswith(".blend")), None)
    if src:
        bpy.ops.wm.open_mainfile(filepath=src)
    vary_materials(amt, edge)
    bpy.ops.wm.save_as_mainfile(filepath=out, compress=True)
