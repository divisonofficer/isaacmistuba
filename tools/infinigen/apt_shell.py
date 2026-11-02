"""Apartment-floor kit shell for P7 (APT5 floorP7_apt), P8 (APT6 floorP8_apt), P9 (APT7 floorP9_apt); user 2026-10-25, SUB2 floorP8_apt r1.
Flag ROOM_APT_SHELL=1 (nothing runs without it; importing this module does nothing); ROOM_APT_SKIP=<floor,walls,light,wardrobe,bath,dining,decor>; ROOM_APT_LIGHT = gain on every added light (default 4.0: the room lights of these scenes are ~10 W fixtures, 1.0 rendered near-black);
ROOM_APT_STYLE = p7 | p8 | p9 (default: read from the blend file name floorP7_apt ... floorP9_apt). Idempotent via scene["ir_apt_shell"]. Kit stage only; every part has its own try/except and writes STATS.
floor     warm oak plank (P9: grey wood) in living / bedroom / kitchen / hallway / office rooms, tile in the baths (replaces the grey carpet tile)
walls     per-unit finishes on each room's wall surface (P8 A: dark grey paint, B: blue/white toile in kitchen + living, white elsewhere + a white panelled wainscot); P7 / P9 palettes from the kit room notes
light     the track spots / rails / ceiling fixtures of bedroom / living / kitchen / hallway go; each room gets recessed warm downlights + a warm area fill + a glow on every lamp (nothing renders near-black)
wardrobe  one real HSSD wardrobe per bedroom on the free wall span (walnut unit A / white unit B, panel-door fallback)
bath      slate + walnut vanity (A) / white subway + brass (B): floor + wall tile, vanity recolour, a real HSSD basin mixer, a glass shower screen
dining    kitchen dining set in a free 2 m patch (A: black round table + cream chairs, B: oval / round white table + white chairs) + pendants (A smoked globes, B pleated drum)
decor     B living: a Christmas tree
"""
from __future__ import annotations

import math
import os
import random

import bpy
from mathutils import Vector

DOORS = ("door", "DoorCasing", "LiteDoor", "PanelDoor", "LouverDoor", "GlassPanelDoor")
SKIP_OBJ = (".floor", ".ceiling", ".wall", ".exterior", ".meshed")
DRESSED = ("bedroom", "living-room", "kitchen", "hallway", "office")

# per scene: unit x-ranges + per-unit finishes. wall: rgb or "toile"; kwall: kitchen wall override; floor: plank colours; wardrobe: rgb; bath: "slate" | "subway"; dining: "black_round" | "white_oval"
STYLES = {
    "p8": {"units": [(0, 12, "A"), (12, 99, "B")], "r2_chairs": "coherent", "pillow_smooth": True, "cloth_soft": True, "ratio2": True, "r2_sofa": True, "curtains": True, "curtains_living": True, "continuous_kitchen": True, "glow_shades": True, "shade_emit": 12.0, "shade_split": True, "pillow_xy": True, "duvet_drop": 0.42, "duvet_trim": 0.3, "mattress_white": True, "lamp_wash": True, "rug_foot": 1.05, "drop_ceiling_junk": True, "close_doors": True,
           "A": {"wall": (0.20, 0.21, 0.23), "floor": ((0.64, 0.5, 0.34), (0.56, 0.42, 0.27)), "wardrobe": (0.28, 0.17, 0.1), "bath": "slate", "dining": "black_round", "pendant": "globe", "tree": False, "kitchen": ((0.2, 0.21, 0.23), (0.7, 0.7, 0.68)), "sofa2": (0.36, 0.39, 0.43),
                 "duvet": (0.88, 0.88, 0.86), "throw": (0.3, 0.32, 0.36), "cushion": (0.5, 0.52, 0.55),
                 "layers": True, "woven": True, "runner": (0.24, 0.26, 0.3), "euro": (0.9, 0.9, 0.88), "bedside": True, "lamp": (0.9, 0.86, 0.78), "rugrx": r"charcoal|dark gr[ae]y|anthracite|black|slate|gr[ae]y", "rug_tone": (0.22, 0.23, 0.26)},
           "B": {"wall": (0.9, 0.89, 0.86), "kwall": "toile", "lwall": "toile", "floor": ((0.7, 0.55, 0.38), (0.62, 0.47, 0.31)), "wardrobe": (0.93, 0.93, 0.91), "bath": "subway", "dining": "white_oval", "pendant": "pleat", "tree": True, "kitchen": ((0.93, 0.93, 0.91), (0.8, 0.7, 0.55)), "sofa2": (0.9, 0.86, 0.78),
                 "duvet": (0.95, 0.95, 0.93), "throw": (0.34, 0.46, 0.66), "cushion": (0.45, 0.58, 0.78),
                 "layers": True, "woven": True, "runner": (0.28, 0.4, 0.62), "euro": (0.95, 0.95, 0.93), "bedside": True, "lamp": (0.95, 0.93, 0.88), "rugrx": r"blue|navy|denim|teal|indigo|white|cream|ivory", "rug_tone": (0.55, 0.65, 0.8)}},
    "p7": {"units": [(0, 10, "A"), (10, 20, "B"), (20, 99, "C")], "r2_chairs": True, "r2_floral_pink": True, "r2_footstool": True, "pillow_smooth": True, "cloth_soft": True, "rect_mirror": True, "r2_glass": True, "curtains_living": True, "ratio2": True, "r2_gallery": True, "r2_globes": True, "curtains": True, "drop_ceiling_junk": True, "glow_shades": True, "shade_emit": 12.0, "shade_split": True, "paint_bedfloor": True, "continuous_kitchen": True, "pillow_xy": True, "floating_vanity": True, "oak_wardrobes": True,
           "A": {"wall": (0.9, 0.84, 0.72), "feature": (0.12, 0.028, 0.016), "kwall": (0.93, 0.86, 0.74), "floor": ((0.74, 0.58, 0.38), (0.66, 0.5, 0.32)), "wardrobe": (0.78, 0.62, 0.42), "bath": "terra", "dining": "white_oval", "pendant": "lantern", "tree": False,
                 "vanity": (0.7, 0.52, 0.32), "mirror": True, "bedrugrx": r"beige|cream|ivory|natural|wool|woven|jute|sand", "duvet": (0.93, 0.9, 0.83), "throw": (0.2, 0.05, 0.03), "cushion": (0.26, 0.06, 0.04), "layers": True, "runner": (0.22, 0.06, 0.035), "euro": (0.93, 0.9, 0.84), "bedside": True, "lamp": (0.93, 0.85, 0.7), "kitchen": ((0.42, 0.24, 0.12), (0.7, 0.55, 0.38)),
                 "sofa": (0.2, 0.035, 0.022), "arm": (0.68, 0.6, 0.5), "rug": "checker"},
           "B": {"wall": (0.95, 0.95, 0.93), "floor": ((0.74, 0.6, 0.42), (0.66, 0.52, 0.36)), "bedfloor": ((0.96, 0.7, 0.03), (0.9, 0.64, 0.02)), "wardrobe": (0.78, 0.62, 0.42), "bath": "subway", "dining": "white_oval", "pendant": "lantern", "tree": False,
                 "vanity": (0.7, 0.52, 0.32), "mirror": True, "bedrugrx": r"gr[ae]y|white|cream|ivory|charcoal|natural", "duvet": "stripe", "throw": (0.78, 0.12, 0.08), "cushion": (0.95, 0.75, 0.05), "layers": True, "runner": (0.08, 0.08, 0.08), "euro": (0.95, 0.95, 0.93), "bedside": True, "lamp": (0.96, 0.8, 0.12), "kitchen": ((0.93, 0.93, 0.91), (0.95, 0.95, 0.93)),
                 "sofa": "stripe", "arm": (0.78, 0.12, 0.08), "rug": "stripe"},
           "C": {"wall": (0.66, 0.67, 0.68), "lwall": (0.62, 0.63, 0.65), "pink": (0.9, 0.64, 0.7), "floor": ((0.76, 0.62, 0.42), (0.68, 0.54, 0.36)), "wardrobe": (0.78, 0.62, 0.42), "bath": "subway", "dining": "white_oval", "pendant": "lantern", "tree": False,
                 "vanity": (0.7, 0.52, 0.32), "mirror": True, "bedfeature": (0.18, 0.18, 0.185), "bedrugrx": r"gr[ae]y|charcoal|slate|silver|white|cream", "duvet": (0.86, 0.86, 0.85), "throw": (0.42, 0.42, 0.42), "cushion": (0.72, 0.5, 0.15), "layers": True, "runner": (0.26, 0.26, 0.27), "euro": (0.88, 0.88, 0.87), "bedside": True, "lamp": (0.92, 0.9, 0.85), "kitchen": ((0.55, 0.57, 0.6), (0.8, 0.8, 0.8)),
                 "sofa": (0.2, 0.21, 0.23), "arm": (0.2, 0.21, 0.23), "rug": (0.5, 0.51, 0.52), "pink_sofa": (0.88, 0.74, 0.74), "pink_arm": (0.86, 0.8, 0.68)}},
    "p9": {"units": [(0, 13, "A"), (13, 99, "B")], "p9_work": True, "r2_chairs": "coherent", "rect_mirror": True, "pale_doors": True, "close_doors": True, "pillow_smooth": True, "cloth_soft": True, "ratio2": True, "r2_sofa": True, "r2_run": True, "glow_shades": True, "shade_emit": 12.0, "shade_split": True, "pillow_xy": True, "duvet_drop": 0.42, "duvet_trim": 0.3, "mattress_white": True, "lamp_wash": True, "rug_foot": 1.05,
           "drop_ceiling_junk": True, "oak_wardrobes": True, "skip_wardrobe_if_oak": True, "floating_vanity": True, "backlit_mirror": True, "curtains": True, "floor_tint": (0.8, 0.78, 0.76),
           "A": {"wall": (0.9, 0.88, 0.82), "floor": ((0.36, 0.355, 0.34), (0.3, 0.295, 0.285)), "wardrobe": (0.8, 0.64, 0.42), "bath": "stone", "dining": "white_oval", "pendant": "pleat", "tree": False, "kitchen": ((0.93, 0.92, 0.88), (0.74, 0.58, 0.38)), "sofa2": (0.78, 0.73, 0.64),
                 "vanity": (0.76, 0.58, 0.37), "mirror": True,
                 "duvet": (0.82, 0.77, 0.66), "throw": (0.42, 0.45, 0.28), "cushion": (0.5, 0.53, 0.34), "layers": True, "woven": True, "runner": (0.38, 0.41, 0.26), "euro": (0.86, 0.82, 0.72), "bedside": True, "lamp": (0.93, 0.9, 0.82),
                 "rugrx": r"jute|sisal|natural|beige|tan|cream|ivory|wool|woven", "rug_tone": (0.75, 0.68, 0.55)},
           "B": {"wall": (0.88, 0.86, 0.84), "kwall": (0.72, 0.5, 0.58), "lwall": (0.9, 0.89, 0.87), "floor": ((0.36, 0.355, 0.34), (0.3, 0.295, 0.285)), "wardrobe": (0.8, 0.64, 0.42), "bath": "stone", "dining": "nook", "pendant": "pleat", "tree": True, "sofa2": (0.1, 0.1, 0.11),
                 "vanity": (0.76, 0.58, 0.37), "mirror": True,
                 "duvet": (0.84, 0.79, 0.68), "throw": (0.46, 0.5, 0.36), "cushion": (0.55, 0.45, 0.32), "layers": True, "woven": True, "runner": (0.42, 0.45, 0.3), "euro": (0.88, 0.84, 0.74), "bedside": True, "lamp": (0.93, 0.9, 0.82),
                 "rugrx": r"jute|sisal|natural|beige|tan|cream|ivory|wool|woven", "rug_tone": (0.75, 0.68, 0.55)}},
}


def _in_box(o, lo, hi):
    a, b = _bb(o)
    return lo[0] < (a[0] + b[0]) / 2 < hi[0] and lo[1] < (a[1] + b[1]) / 2 < hi[1]


def _bb(o):
    p = [o.matrix_world @ Vector(c) for c in o.bound_box]
    return [min(q[i] for q in p) for i in range(3)], [max(q[i] for q in p) for i in range(3)]


def _ra():
    import real_assets
    return real_assets


def _flat(name, rgb, rough=0.5, metal=0.0):
    from room_planner import proc_assets as pa
    m = pa._flat(name, rgb, rough, metal); m["weathered"] = True; m["apt_rgb"] = tuple(rgb)
    return m


def _emit(name, rgb, s):
    m = _flat(name, rgb, 0.4); b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Emission Color"].default_value = (*rgb, 1.0); b.inputs["Emission Strength"].default_value = s
    return m


def _gain():
    return float(os.environ.get("ROOM_APT_LIGHT") or 1.6)      # P8 r3 fix: the lights were above the ceiling; with them below it 4.0 overexposed (mean 0.5), 1.6 targets ~0.2


def _light(name, kind, loc, w, rgb=(1.0, 0.82, 0.6), **kw):
    ld = bpy.data.lights.new(name, kind); ld.energy = w * _gain(); ld.color = rgb
    if kind == "AREA":
        ld.shape = "RECTANGLE"; ld.size = kw.get("sx", 1.5); ld.size_y = kw.get("sy", 1.5)
    elif kind == "SPOT":
        ld.spot_size = math.radians(85); ld.spot_blend = 0.6; ld.shadow_soft_size = 0.05
    else:
        ld.shadow_soft_size = kw.get("r", 0.08)
    o = bpy.data.objects.new(name, ld); o.location = loc; bpy.context.scene.collection.objects.link(o)
    if kind == "SPOT":
        o.rotation_euler = (0, 0, 0)                          # a spot points down -Z by default
    return o


def _style():
    key = (os.environ.get("ROOM_APT_STYLE") or "").lower()
    if not key:
        fp = bpy.data.filepath
        key = next((k for k, tag in (("p7", "floorP7"), ("p8", "floorP8"), ("p9", "floorP9")) if tag in fp or tag.lower() in fp.lower()), "p8")
    return STYLES[key]


def _unit(st, x):
    return next((u for a, b, u in st["units"] if a <= x < b), st["units"][-1][2])


def _rooms():
    out = {}
    for o in bpy.data.objects:
        if o.type == "MESH" and o.name.endswith(".floor") and "/" in o.name:
            lo, hi = _bb(o); n = o.name[:-6]
            out[n] = (lo, hi, n.split("_0/")[0])
    return out


def _obstacles(lo, hi, refs=False):
    """xy rects (x0, x1, y0, y1) of everything standing in the room: furniture >0.25 m tall, doors padded 0.9 m (swing)."""
    obs = []
    for o in bpy.data.objects:
        if o.type != "MESH" or o.name.endswith(SKIP_OBJ) or o.name.startswith(("Baseboard", "Sprinkler", "apt_")) or ("/" in o.name and "(" not in o.name):
            continue
        a, b = _bb(o)
        if not (b[0] > lo[0] and a[0] < hi[0] and b[1] > lo[1] and a[1] < hi[1]):
            continue
        if o.name.startswith(DOORS):
            obs.append((a[0] - 0.9, b[0] + 0.9, a[1] - 0.9, b[1] + 0.9, None))
        elif b[2] - a[2] > 0.25 and a[2] < 1.2 and (b[0] - a[0]) < 8 and (b[1] - a[1]) < 8:
            obs.append((a[0] - 0.05, b[0] + 0.05, a[1] - 0.05, b[1] + 0.05, o))
    return obs if refs else [q[:4] for q in obs]


def _free_patch(lo, hi, obs, w, d, margin=0.45, step=0.25):
    """First free w x d rectangle in the room (centre x, centre y) or None; scans from the room centre outwards."""
    cx0, cy0 = (lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2; cands = []
    x = lo[0] + margin + w / 2
    while x <= hi[0] - margin - w / 2:
        y = lo[1] + margin + d / 2
        while y <= hi[1] - margin - d / 2:
            cands.append(((x - cx0) ** 2 + (y - cy0) ** 2, x, y)); y += step
        x += step
    for _, x, y in sorted(cands):
        r = (x - w / 2, x + w / 2, y - d / 2, y + d / 2)
        if not any(r[0] < q[1] and q[0] < r[1] and r[2] < q[3] and q[2] < r[3] for q in obs):
            return x, y
    return None


def _wall_span(room, lo, hi, obs, L, depth=0.65):
    """A free L-long strip against one wall: (x, y, facing_yaw, wall_side) for the first side/offset that clears every obstacle, else None. Prefers the longest walls."""
    import wall_face
    sides = sorted("SNWE", key=lambda s: -((hi[0] - lo[0]) if s in "SN" else (hi[1] - lo[1])))
    for s in sides:
        ins = wall_face.inset(room, s, 0.11)
        along = (lo[0] + 0.3, hi[0] - 0.3) if s in "SN" else (lo[1] + 0.3, hi[1] - 0.3)
        u = along[0] + L / 2
        while u <= along[1] - L / 2:
            if s == "S":
                x, y, yaw, r = u, lo[1] + ins + depth / 2, math.pi / 2, (u - L / 2, u + L / 2, lo[1], lo[1] + ins + depth)
            elif s == "N":
                x, y, yaw, r = u, hi[1] - ins - depth / 2, -math.pi / 2, (u - L / 2, u + L / 2, hi[1] - ins - depth, hi[1])
            elif s == "W":
                x, y, yaw, r = lo[0] + ins + depth / 2, u, 0.0, (lo[0], lo[0] + ins + depth, u - L / 2, u + L / 2)
            else:
                x, y, yaw, r = hi[0] - ins - depth / 2, u, math.pi, (hi[0] - ins - depth, hi[0], u - L / 2, u + L / 2)
            if not any(r[0] < q[1] and q[0] < r[1] and r[2] < q[3] and q[2] < r[3] for q in obs):
                return x, y, yaw, s, r
            u += 0.2
    return None


REMOVABLE = ("AboDresser", "AboArmchair", "AboBookcase", "BasketBase", "BedBench", "AboVase", "AboFloorlamp", "AboSide", "AboDesk", "AboCafechair", "AboNightstand", "BookStack", "AboPlanter", "AboCoffee", "AboRug")


def _wall_span_clear(room, lo, hi, L, depth=0.65):
    """A wall strip the wardrobe can take: free, or blocked only by small loose furniture (dresser, armchair, desk ...), which is removed. Prefers the fewest removals, then the longest wall."""
    import wall_face
    obs = _obstacles(lo, hi, refs=True); best = None
    for s in "SNWE":
        ins = wall_face.inset(room, s, 0.11); along = (lo[0] + 0.3, hi[0] - 0.3) if s in "SN" else (lo[1] + 0.3, hi[1] - 0.3)
        u = along[0] + L / 2
        while u <= along[1] - L / 2:
            if s == "S":
                x, y, yaw, r = u, lo[1] + ins + depth / 2, math.pi / 2, (u - L / 2, u + L / 2, lo[1], lo[1] + ins + depth)
            elif s == "N":
                x, y, yaw, r = u, hi[1] - ins - depth / 2, -math.pi / 2, (u - L / 2, u + L / 2, hi[1] - ins - depth, hi[1])
            elif s == "W":
                x, y, yaw, r = lo[0] + ins + depth / 2, u, 0.0, (lo[0], lo[0] + ins + depth, u - L / 2, u + L / 2)
            else:
                x, y, yaw, r = hi[0] - ins - depth / 2, u, math.pi, (hi[0] - ins - depth, hi[0], u - L / 2, u + L / 2)
            hit = [q for q in obs if r[0] < q[1] and q[0] < r[1] and r[2] < q[3] and q[2] < r[3]]
            if all(q[4] is not None and q[4].name.startswith(REMOVABLE) for q in hit):
                key = (len(hit), -((hi[0] - lo[0]) if s in "SN" else (hi[1] - lo[1])))
                if best is None or key < best[0]:
                    best = (key, x, y, yaw, s, [q[4] for q in hit])
            u += 0.2
    return best


def _set_slots(obj, mat):
    if obj is not None:
        for sl in obj.material_slots:
            sl.material = mat


# ---------------------------------------------------------------- materials ----------------------------------------------------------------

def _plank(name, c1, c2, tint=(0.62, 0.52, 0.42)):
    m = bpy.data.materials.get(name)
    if m is not None:
        return m
    m = _flat(name, c1, 0.4); nt = m.node_tree; N, L = nt.nodes, nt.links; b = N["Principled BSDF"]
    tc = N.new("ShaderNodeTexCoord"); br = N.new("ShaderNodeTexBrick"); L.new(tc.outputs["Object"], br.inputs["Vector"])
    br.offset = 0.5; br.inputs["Scale"].default_value = 1.0; br.inputs["Brick Width"].default_value = 1.2; br.inputs["Row Height"].default_value = 0.18; br.inputs["Mortar Size"].default_value = 0.002
    br.inputs["Color1"].default_value = (*c1, 1); br.inputs["Color2"].default_value = (*c2, 1); br.inputs["Mortar"].default_value = (c2[0] * 0.5, c2[1] * 0.5, c2[2] * 0.5, 1)
    wv = N.new("ShaderNodeTexWave"); wv.wave_type = "BANDS"; wv.bands_direction = "X"; wv.inputs["Scale"].default_value = 30.0; wv.inputs["Distortion"].default_value = 6.0; wv.inputs["Detail"].default_value = 3.0
    L.new(tc.outputs["Object"], wv.inputs["Vector"])
    mx = N.new("ShaderNodeMix"); mx.data_type = "RGBA"; mx.blend_type = "MULTIPLY"; mx.inputs["B"].default_value = (*tint, 1)
    L.new(br.outputs["Color"], mx.inputs["A"]); L.new(wv.outputs["Fac"], mx.inputs["Factor"]); L.new(mx.outputs["Result"], b.inputs["Base Color"])
    return m


def _paint_yellow():
    m = bpy.data.materials.get("ir_apt_floor_paint_yellow")
    if m is not None:
        return m
    m = _flat("ir_apt_floor_paint_yellow", (0.95, 0.75, 0.1), 0.55); b = m.node_tree.nodes["Principled BSDF"]
    for sock in ("Base Color", "Roughness", "Normal"):                  # pa._flat's surface-detail noise would read as dirt on paint
        for lk in list(b.inputs[sock].links):
            m.node_tree.links.remove(lk)
    b.inputs["Base Color"].default_value = (0.95, 0.75, 0.1, 1); b.inputs["Roughness"].default_value = 0.55
    for k_ in ("Emission Strength",):
        b.inputs[k_].default_value = 0.0
    return m


def _tile(name, rgb, size, grout_rgb, rough=0.2, brick=False):
    """Tile / subway wall + floor shader (object space): square cells, or 2:1 running-bond bricks."""
    m = bpy.data.materials.get(name)
    if m is not None:
        return m
    m = _flat(name, rgb, rough); nt = m.node_tree; N, L = nt.nodes, nt.links; b = N["Principled BSDF"]
    tc = N.new("ShaderNodeTexCoord"); br = N.new("ShaderNodeTexBrick"); L.new(tc.outputs["Object"], br.inputs["Vector"])
    br.offset = 0.5 if brick else 0.0; br.inputs["Scale"].default_value = 1.0 / size
    br.inputs["Brick Width"].default_value = 2.0 if brick else 1.0; br.inputs["Row Height"].default_value = 1.0; br.inputs["Mortar Size"].default_value = 0.012
    br.inputs["Color1"].default_value = (*rgb, 1); br.inputs["Color2"].default_value = (rgb[0] * 0.93, rgb[1] * 0.93, rgb[2] * 0.93, 1); br.inputs["Mortar"].default_value = (*grout_rgb, 1)
    L.new(br.outputs["Color"], b.inputs["Base Color"])
    for sock in ("Roughness", "Normal"):                              # r4: pa._flat's surface-detail noise on near-black slate/tile read as dirt stains and scratches
        for lk in list(b.inputs[sock].links):
            nt.links.remove(lk)
    return m


def _toile(name="ir_apt_toile2"):
    """pkg_h_apt: small botanical rose/vine repeat, projected in world metres."""
    import numpy as np
    m = bpy.data.materials.get(name)
    if m is not None and m.get("pkg_h_botanical"):
        return m
    m = m or bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree; nt.nodes.clear(); N, links = nt.nodes, nt.links
    out = N.new("ShaderNodeOutputMaterial"); bs = N.new("ShaderNodeBsdfPrincipled")
    bs.inputs["Roughness"].default_value = .78
    links.new(bs.outputs["BSDF"], out.inputs["Surface"])
    image_name = "pkg_h_apt_blue_botanical_042x060"
    im = bpy.data.images.get(image_name)
    if im is None:
        n = 512
        yy, xx = np.mgrid[0:n, 0:n].astype(float) / n
        ink = np.zeros((n, n), dtype=float)
        # Two climbing stems per repeat, with leaves branching to either side.
        for stem in (.23, .73):
            curve = stem + .07 * np.sin(yy * 2 * math.pi)
            ink = np.maximum(ink, np.exp(-((xx - curve) / .0035) ** 2) * .65)
            for j in range(7):
                y = (j + .5) / 7
                x = stem + .07 * math.sin(y * 2 * math.pi)
                side = 1 if j % 2 else -1
                dx, dy = xx - (x + side * .035), yy - (y + .018)
                u = dx * side * .8 + dy * .6
                v = -dx * .6 + dy * side * .8
                leaf = (u / .045) ** 2 + (v / .012) ** 2
                ink = np.maximum(ink, np.where(leaf < 1, .45 + .3 * np.cos(u * 55), 0))
        # Five-petal flower clusters, fine contours and stippled centres.
        for x, y in ((.28,.18),(.68,.48),(.30,.80)):
            dx, dy = xx - x, (yy - y) * .60 / .42
            rad = np.sqrt(dx * dx + dy * dy)
            angle = np.arctan2(dy, dx)
            edge = .045 + .012 * np.cos(5 * angle)
            petal = np.exp(-((rad - edge) / .003) ** 2)
            veins = np.where(rad < edge, .16 * (1 + np.cos(5 * angle)) * rad / .05, 0)
            ink = np.maximum(ink, np.maximum(petal * .85, veins))
            ink = np.maximum(ink, np.exp(-(rad / .009) ** 2) * .8)
        ground = np.array([.84,.83,.78]); blue = np.array([.06,.15,.33])
        rgb = ground[None,None,:] * (1 - ink[:,:,None]) + blue[None,None,:] * ink[:,:,None]
        rgba = np.ones((n,n,4), dtype=np.float32); rgba[:,:,:3] = rgb
        im = bpy.data.images.new(image_name, width=n, height=n, alpha=True)
        im.colorspace_settings.name = "Non-Color"
        im.pixels.foreach_set(rgba.ravel()); im.pack()
    tex = N.new("ShaderNodeTexImage"); tex.image = im; tex.extension = "REPEAT"
    geo = N.new("ShaderNodeNewGeometry"); sep = N.new("ShaderNodeSeparateXYZ")
    links.new(geo.outputs["Position"], sep.inputs[0])
    add = N.new("ShaderNodeMath"); add.operation = "ADD"
    links.new(sep.outputs["X"], add.inputs[0]); links.new(sep.outputs["Y"], add.inputs[1])
    sx = N.new("ShaderNodeMath"); sx.operation = "DIVIDE"; sx.inputs[1].default_value = .42
    sz = N.new("ShaderNodeMath"); sz.operation = "DIVIDE"; sz.inputs[1].default_value = .60
    links.new(add.outputs[0], sx.inputs[0]); links.new(sep.outputs["Z"], sz.inputs[0])
    uv = N.new("ShaderNodeCombineXYZ")
    links.new(sx.outputs[0], uv.inputs["X"]); links.new(sz.outputs[0], uv.inputs["Y"])
    links.new(uv.outputs[0], tex.inputs["Vector"]); links.new(tex.outputs["Color"], bs.inputs["Base Color"])
    m["weathered"] = True; m["pkg_h_botanical"] = 1
    return m


def _wall_mat(spec, room_type, unit):
    if spec == "toile":
        return _toile()
    if spec == "stripe":
        return _stripe_mat("ir_apt_wall_stripe", scale=18.0)
    return _flat(f"ir_apt_paint_{int(spec[0] * 100)}_{int(spec[1] * 100)}_{int(spec[2] * 100)}", tuple(spec), 0.75)


def _recolour(o, rgb, name, rough=0.5):
    """Largest-area slot of an imported piece takes a flat material (upholstery / cabinet fronts)."""
    if o is None or o.type != "MESH" or not o.data.materials:
        return
    area = {}
    for p in o.data.polygons:
        area[p.material_index] = area.get(p.material_index, 0.0) + p.area
    i = max(area, key=area.get)
    if i < len(o.data.materials):
        o.data = o.data.copy(); o.data.materials[i] = _flat(name, rgb, rough)


# ---------------------------------------------------------------- parts ----------------------------------------------------------------

def _floor(st, stats):
    n = 0
    for r, (lo, hi, t) in _rooms().items():
        u = st[_unit(STY, (lo[0] + hi[0]) / 2)]
        f = bpy.data.objects.get(f"{r}.floor")
        if t in DRESSED:
            c1, c2 = u["bedfloor"] if (t == "bedroom" and u.get("bedfloor")) else u["floor"]
            if t == "bedroom" and u.get("bedfloor") and STY.get("paint_bedfloor"):
                _set_slots(f, _paint_yellow()); n += 1                      # P7 r6: a saturated painted yellow, not pale tile / planks
                continue
            tint = STY.get("floor_tint")                                    # p9: grey wood (the default tint warms every plank to oak)
            _set_slots(f, _plank(f"ir_apt_plank_{int(c1[0] * 100)}_{int(c1[1] * 100)}" + ("_g" if tint else ""), c1, c2, *((tint,) if tint else ()))); n += 1
        elif t == "bathroom":
            if u["bath"] == "slate":
                _set_slots(f, _tile("ir_apt_slate_floor", (0.14, 0.15, 0.16), 0.5, (0.07, 0.07, 0.08), 0.3))
            elif u["bath"] == "stone":                                     # p9 REF: large-format light grey stone
                _set_slots(f, _tile("ir_apt_stone_floor", (0.56, 0.56, 0.55), 0.6, (0.42, 0.42, 0.41), 0.3)); n += 1
            elif u["bath"] == "terra":
                _set_slots(f, _tile("ir_apt_terra_floor", (0.74, 0.66, 0.54), 0.3, (0.5, 0.44, 0.36), 0.25)); n += 1
            else:
                _set_slots(f, _tile("ir_apt_subway_floor", (0.82, 0.82, 0.8), 0.3, (0.55, 0.55, 0.53), 0.25)); n += 1
    stats["apt_floor"] = n


def _walls(st, stats):
    import wall_face
    n = 0
    from room_planner import proc_boutique_flagship as fl
    for r, (lo, hi, t) in _rooms().items():
        u = st[_unit(STY, (lo[0] + hi[0]) / 2)]; w = bpy.data.objects.get(f"{r}.wall")
        if t == "bathroom":
            _set_slots(w, _tile("ir_apt_slate_wall", (0.17, 0.18, 0.19), 0.45, (0.08, 0.08, 0.09), 0.35) if u["bath"] == "slate"
                       else _tile("ir_apt_stone_wall", (0.6, 0.6, 0.58), 0.6, (0.44, 0.44, 0.43), 0.3) if u["bath"] == "stone"
                       else _tile("ir_apt_terra_wall", (0.22, 0.06, 0.035), 0.15, (0.15, 0.05, 0.03), 0.2, brick=True) if u["bath"] == "terra"
                       else _tile("ir_apt_subway_wall", (0.95, 0.95, 0.93), 0.15, (0.7, 0.7, 0.68), 0.15, brick=True)); n += 1
            continue
        if t not in DRESSED:
            continue
        spec = u.get("kwall") if t == "kitchen" and u.get("kwall") else u.get("lwall") if t == "living-room" and u.get("lwall") else u["wall"]
        if t == "living-room" and u.get("pink") and lo[1] > 6.5:                    # P7 unit C's second living room is the pink-walled sitting room
            spec = u["pink"]
        _set_slots(w, _wall_mat(spec, t, u)); n += 1
        if spec == "toile" or u is st.get("B"):                       # white panelled wainscot under a toile wall (P8 B)
            if spec == "toile":
                wain = _flat("ir_apt_wainscot", (0.95, 0.95, 0.93), 0.5); prims = []
                cas = [(c, _bb(c)) for c in bpy.data.objects if c.type == "MESH" and c.name.startswith("DoorCasingFactory")]
                for s in "SNWE":
                    ins = wall_face.inset(r, s, 0.11); z0, z1 = lo[2] + 0.1, lo[2] + 1.05
                    ax = 0 if s in "SN" else 1                                   # span axis; p8 r11: break the panel at every door casing instead of running across the openings
                    a0, a1 = lo[ax] + 0.1, hi[ax] - 0.1
                    wv = (lo[1] + ins) if s == "S" else (hi[1] - ins) if s == "N" else (lo[0] + ins) if s == "W" else (hi[0] - ins)
                    cuts = sorted((b0[ax] - 0.03, b1[ax] + 0.03) for c, (b0, b1) in cas
                                  if abs((b0[1 - ax] + b1[1 - ax]) / 2 - wv) < 0.4 and a0 - 0.5 < (b0[ax] + b1[ax]) / 2 < a1 + 0.5 and (b1[ax] - b0[ax]) > 0.6)
                    segs, p0 = [], a0
                    for c0, c1 in cuts:
                        if c0 > p0 + 0.05: segs.append((p0, min(c0, a1)))
                        p0 = max(p0, c1)
                    if a1 > p0 + 0.05: segs.append((p0, a1))
                    for g0, g1 in segs:
                        if s in "SN":
                            y = (lo[1] + ins + 0.014) if s == "S" else (hi[1] - ins - 0.014)
                            prims.append(("box", (g0 + g1) / 2, y, (z0 + z1) / 2, g1 - g0, 0.028, z1 - z0))
                        else:
                            x = (lo[0] + ins + 0.014) if s == "W" else (hi[0] - ins - 0.014)
                            prims.append(("box", x, (g0 + g1) / 2, (z0 + z1) / 2, 0.028, g1 - g0, z1 - z0))
                fl.mesh_object(f"apt_Wainscot({r})", [(wain, prims)], bevel=True)
    stats["apt_walls"] = n


def _zc(r, lo):
    """Underside of the room's real ceiling slab (P8 r3: lights at floor + 2.45 sat ABOVE the 2.48 ceiling and lit nothing): ceiling object bbox min z - 1 cm."""
    c = bpy.data.objects.get(f"{r}.ceiling")
    return (min(_bb(c)[0][2], _bb(c)[1][2]) - 0.01) if c is not None else lo[2] + 2.35


def _lights(st, stats):
    n = rm = 0
    kill = ("TrackSpotFactory", "TrackRailFactory", "AboCeilingFixtureFactory", "CeilingLightFactory")
    for r, (lo, hi, t) in _rooms().items():
        if t not in DRESSED:
            continue
        zc = _zc(r, lo)
        if st.get("drop_ceiling_junk"):                               # P8 r7: generation's ceiling ducts / soffits / beams / pipes cut every bedroom lengthways (the reference has a plain ceiling): remove them in dressed rooms
            for o in list(bpy.data.objects):
                if o.type == "MESH" and o.name.startswith(("DuctFactory", "SoffitFactory", "CeilingBeamFactory", "PipeFactory")):
                    a_, b_ = _bb(o)
                    if lo[0] - 0.2 < (a_[0] + b_[0]) / 2 < hi[0] + 0.2 and lo[1] - 0.2 < (a_[1] + b_[1]) / 2 < hi[1] + 0.2 and b_[2] > 1.9:
                        bpy.data.objects.remove(o, do_unlink=True); rm += 1
        for o in list(bpy.data.objects):
            a = o.location
            if (o.type == "LIGHT" and o.data.type in ("SPOT", "POINT") and lo[0] - 0.1 < a.x < hi[0] + 0.1 and lo[1] - 0.1 < a.y < hi[1] + 0.1 and a.z > 2.0) or \
               (o.type == "MESH" and o.name.startswith(kill) and lo[0] - 0.2 < (_bb(o)[0][0] + _bb(o)[1][0]) / 2 < hi[0] + 0.2 and lo[1] - 0.2 < (_bb(o)[0][1] + _bb(o)[1][1]) / 2 < hi[1] + 0.2 and _bb(o)[1][2] > 2.0):
                bpy.data.objects.remove(o, do_unlink=True); rm += 1
        W, D = hi[0] - lo[0], hi[1] - lo[1]; nx, ny = max(1, round(W / 1.9)), max(1, round(D / 1.9))
        disc = _emit("ir_apt_dl", (1.0, 0.85, 0.65), 25.0); fl = None
        from room_planner import proc_boutique_flagship as fl
        prims = []
        for i in range(nx):
            for j in range(ny):
                x, y = lo[0] + W * (i + 0.5) / nx, lo[1] + D * (j + 0.5) / ny
                prims.append(("cyl", (x, y, zc - 0.012), (x, y, zc - 0.002), 0.06, 20))
                _light(f"ir_apt_dl_{r}_{i}_{j}", "SPOT", (x, y, zc - 0.05), 45, (1.0, 0.8, 0.58)); n += 1
        fl.mesh_object(f"apt_Downlights({r})", [(disc, prims)], bevel=False)
        _light(f"ir_apt_fill_{r}", "AREA", ((lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, zc - 0.1), 40 * (W * D) ** 0.5 / 3.0, (1.0, 0.84, 0.66), sx=W * 0.6, sy=D * 0.6); n += 1
    for o in list(bpy.data.objects):                                  # a warm glow on every lamp
        if o.type == "MESH" and o.name.startswith(("AboFloorlampFactory", "AboTableLampFactory")):
            if st.get("glow_shades"):
                stats["apt_shades_glow"] = stats.get("apt_shades_glow", 0) + _glow_shade(o, st.get("shade_emit", 6.0), st.get("shade_split", False))
            a, b = _bb(o); _light(f"ir_apt_lamp_{o.name[:14]}", "POINT", ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, b[2] - 0.18), 35, (1.0, 0.78, 0.5), r=0.12); n += 1
    stats["apt_lights"] = n; stats["apt_removed_fixtures"] = rm


def _wardrobes(st, stats):
    ra = _ra(); n = fb = 0
    for r, (lo, hi, t) in _rooms().items():
        if t != "bedroom":
            continue
        u = st[_unit(STY, (lo[0] + hi[0]) / 2)]
        if st.get("skip_wardrobe_if_oak") and any(o.type == "MESH" and o.name.startswith("OakWardrobeFactory") and _in_box(o, lo, hi) for o in bpy.data.objects):
            continue                                                       # p9: the layout's own oak wardrobe wall is recoloured below instead of adding a second one
        L = min(2.4, max(1.4, 0.4 * max(hi[0] - lo[0], hi[1] - lo[1])))
        spot = None
        for L in (L, 1.8, 1.4, 1.2, 0.9):                                     # the longest free strip that fits
            spot = _wall_span_clear(r, lo, hi, L, depth=0.62)
            if spot is not None:
                break
        if spot is None:
            continue
        _k, x, y, yaw, s, gone = spot
        for g in gone:
            bpy.data.objects.remove(g, do_unlink=True)
        o = ra.hssd(r"wardrobe|closet", 11 + n, x, y, lo[2], yaw, fit=(L, 0.65, 2.25), size=(1.2, 3.2), grow=True)
        if o is not None:
            _recolour(o, u["wardrobe"], f"ir_apt_wardrobe_{int(u['wardrobe'][0] * 100)}", 0.45); o.name = f"apt_Wardrobe({r})"
        else:
            fb += 1; _wardrobe_panels(r, x, y, yaw, L, lo[2], u["wardrobe"])
        n += 1
    oak = 0
    if st.get("oak_wardrobes"):                                                   # P7 r5: bedroom_0-0's layout OakWardrobeFactory stayed dark walnut (REF: light oak): every big slot of those wardrobes takes the unit's oak
        for r, (lo, hi, t) in _rooms().items():
            if t != "bedroom":
                continue
            u = st[_unit(STY, (lo[0] + hi[0]) / 2)]
            for o in list(bpy.data.objects):
                if o.type == "MESH" and o.name.startswith("OakWardrobeFactory") and lo[0] < (_bb(o)[0][0] + _bb(o)[1][0]) / 2 < hi[0] and lo[1] < (_bb(o)[0][1] + _bb(o)[1][1]) / 2 < hi[1]:
                    area = {}
                    for p_ in o.data.polygons:
                        area[p_.material_index] = area.get(p_.material_index, 0.0) + p_.area
                    tot = sum(area.values()) or 1.0; o.data = o.data.copy()
                    for i_, a_ in area.items():
                        if a_ / tot > 0.08 and i_ < len(o.data.materials):
                            o.data.materials[i_] = _flat(f"ir_apt_wardrobe_{int(u['wardrobe'][0] * 100)}", u["wardrobe"], 0.45)
                    oak += 1
    stats["apt_wardrobes"] = {"placed": n, "panel_fallback": fb, "oak_recoloured": oak}


def _wardrobe_panels(room, x, y, yaw, L, z0, rgb):
    from room_planner import proc_boutique_flagship as fl
    body = _flat(f"ir_apt_wardrobe_{int(rgb[0] * 100)}", rgb, 0.45); brass = _flat("ir_apt_brass", (0.72, 0.52, 0.22), 0.3, 1.0)
    c, s = math.cos(yaw), math.sin(yaw); prims, hand = [], []

    def P(u, d, z, su, sd, sz):                                      # u along the wardrobe, d out of the wall (front +d)
        return ("box", x + c * d - s * u, y + s * d + c * u, z, *((su, sd) if abs(s) > 0.5 else (sd, su)), sz)
    n = max(2, round(L / 0.6)); pw = L / n
    prims.append(P(0, -0.3, z0 + 1.15, L, 0.05, 2.3))
    for i in range(n):
        u = -L / 2 + (i + 0.5) * pw
        prims += [P(u, 0.0, z0 + 1.15, pw - 0.01, 0.03, 2.25), P(u, 0.02, z0 + 1.15, pw - 0.14, 0.012, 2.05)]
        hand.append(P(u + (0.2 if i % 2 else -0.2), 0.04, z0 + 1.1, 0.012, 0.015, 0.3))
    fl.mesh_object(f"apt_Wardrobe({room})", [(body, prims), (brass, hand)], bevel=True)


def _woven_mat(name, rgb, contrast=0.07, scale=160.0):
    """P8 r7: a flat blue throw read as angular patchwork blocks; a fine woven fabric (two close tones, high-frequency noise + bump) reads as cloth."""
    m = bpy.data.materials.get(name)
    if m is not None:
        return m
    m = _flat(name, rgb, 0.92); nt = m.node_tree; N, L = nt.nodes, nt.links; b = N["Principled BSDF"]
    tc = N.new("ShaderNodeTexCoord"); no = N.new("ShaderNodeTexNoise"); no.inputs["Scale"].default_value = scale; no.inputs["Detail"].default_value = 2.0
    mx = N.new("ShaderNodeMix"); mx.data_type = "RGBA"; mx.inputs["A"].default_value = (*rgb, 1); mx.inputs["B"].default_value = (*(min(1.0, c * (1 + contrast)) for c in rgb), 1)
    bu = N.new("ShaderNodeBump"); bu.inputs["Strength"].default_value = 0.12; bu.inputs["Distance"].default_value = 0.003
    L.new(tc.outputs["Object"], no.inputs["Vector"]); L.new(no.outputs["Fac"], mx.inputs["Factor"]); L.new(mx.outputs["Result"], b.inputs["Base Color"]); L.new(no.outputs["Fac"], bu.inputs["Height"]); L.new(bu.outputs["Normal"], b.inputs["Normal"])
    return m


def _stripe_mat(name="ir_apt_bed_stripe", scale=9.0):
    m = bpy.data.materials.get(name)
    if m is not None:
        return m
    m = _flat(name, (0.9, 0.9, 0.9), 0.85); nt = m.node_tree; N, L = nt.nodes, nt.links; b = N["Principled BSDF"]
    tc = N.new("ShaderNodeTexCoord"); wv = N.new("ShaderNodeTexWave"); wv.wave_type = "BANDS"; wv.bands_direction = "X"; wv.inputs["Scale"].default_value = scale; wv.inputs["Distortion"].default_value = 0.0
    gt = N.new("ShaderNodeMath"); gt.operation = "GREATER_THAN"; gt.inputs[1].default_value = 0.5
    mx = N.new("ShaderNodeMix"); mx.data_type = "RGBA"; mx.inputs["A"].default_value = (0.95, 0.95, 0.93, 1); mx.inputs["B"].default_value = (0.05, 0.05, 0.05, 1)
    L.new(tc.outputs["Object"], wv.inputs["Vector"]); L.new(wv.outputs["Fac"], gt.inputs[0]); L.new(gt.outputs["Value"], mx.inputs["Factor"]); L.new(mx.outputs["Result"], b.inputs["Base Color"])
    return m




def _bed_slot(lo, hi, L=2.1, W=1.5):
    """First free L x W slot with its head to a wall, clear of every object and 0.9 m from the doors: (wall, rect) or None."""
    obs = []
    for o in bpy.data.objects:
        if o.type != "MESH" or o.name.endswith((".floor", ".ceiling", ".wall", ".exterior")) or o.name.startswith(("Baseboard",)) or ("/" in o.name and "(" not in o.name and "." not in o.name):      # not the room-shell mesh 'bedroom_0/8'
            continue
        b0, b1 = _bb(o)
        if b1[2] > 0.25 and b0[2] < 2.0 and b1[0] > lo[0] and b0[0] < hi[0] and b1[1] > lo[1] and b0[1] < hi[1]:
            pad = 0.3 if o.name.startswith(("LiteDoor", "GlassPanelDoor", "PanelDoor", "door", "DoorCasing")) else 0.05      # r6: 0.9 m left bedroom_0/8 (two doors) no slot; the door.* bbox already spans the swing
            obs.append((b0[0] - pad, b1[0] + pad, b0[1] - pad, b1[1] + pad))
    for wall in ("N", "S", "W", "E"):
        along = (lo[0], hi[0]) if wall in ("N", "S") else (lo[1], hi[1]); u = along[0] + 0.5 + W / 2
        while u < along[1] - 0.5 - W / 2:
            r = {"S": (u - W / 2, u + W / 2, lo[1] + 0.02, lo[1] + 0.02 + L), "N": (u - W / 2, u + W / 2, hi[1] - 0.02 - L, hi[1] - 0.02),
                 "W": (lo[0] + 0.02, lo[0] + 0.02 + L, u - W / 2, u + W / 2), "E": (hi[0] - 0.02 - L, hi[0] - 0.02, u - W / 2, u + W / 2)}[wall]
            if r[0] >= lo[0] and r[1] <= hi[0] and r[2] >= lo[1] and r[3] <= hi[1] and not any(r[0] < q[1] and q[0] < r[1] and r[2] < q[3] and q[2] < r[3] for q in obs):
                return wall, r
            u += 0.1
    return None




def _spare_bed(r, lo, hi, n):
    """P8 r4: a bedroom whose layout bed was refused (bedroom_0/1: no bed at all) gets a real ABO bed in the first free slot (head to a wall, clear of objects and doors)."""
    ra = _ra(); bpy.context.view_layer.update(); best = None
    for o in [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith(("PilasterFactory", "ColumnFactory", "RoundPillarFactory")) and lo[0] < (_bb(o)[0][0] + _bb(o)[1][0]) / 2 < hi[0] and lo[1] < (_bb(o)[0][1] + _bb(o)[1][1]) / 2 < hi[1]]:
        bpy.data.objects.remove(o, do_unlink=True)                          # a 2.7 m deep room: the generator's pilasters sit where the bed has to go
    for pass_ in (0, 1):
        for W in (1.5, 1.4):
            best = _bed_slot(lo, hi, 2.1, W)
            if best is not None:
                break
        if best is not None or pass_:
            break
        for o in [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith("AboNightstandFactory") and lo[0] < (_bb(o)[0][0] + _bb(o)[1][0]) / 2 < hi[0] and lo[1] < (_bb(o)[0][1] + _bb(o)[1][1]) / 2 < hi[1]]:
            bpy.data.objects.remove(o, do_unlink=True)                      # the layout's nightstands flank a bed it could not place: they make way for the real one
        bpy.context.view_layer.update()
    if best is None:
        return False
    wall, rc = best; cx, cy = (rc[0] + rc[1]) / 2, (rc[2] + rc[3]) / 2
    hx = {"W": (-1, 0), "E": (1, 0), "S": (0, -1), "N": (0, 1)}[wall]
    o = ra.abo("bed", 17 + n, cx, cy, lo[2], math.atan2(-hx[1], -hx[0]), fit=(W + 0.15, 2.2, 1.4))
    if o is None:
        return False
    o.name = f"apt_SpareBed({r})"
    return True


def _dims(st, kind, ax):
    """(sx, sy, hscale): pillow footprints; P7 r5: the lozenge pillows read too large -> 0.35 x 0.5 sleeping / 0.28 x 0.5 euro / 0.12 x 0.36 cushion, 15 % lower."""
    d = {"pillow": (0.2, 0.62), "euro": (0.2, 0.62), "cushion": (0.14, 0.42)}[kind]; h = 1.0
    if st.get("pillow_xy"):
        d = {"pillow": (0.35, 0.5), "euro": (0.22, 0.5), "cushion": (0.12, 0.36)}[kind]; h = 0.85
    return (d if ax else d[::-1]), h


def _bedding(st, stats):
    """P7 r1: Infinigen's own bed dressing (a rigid blanket slab, a loose throw 'board', stiff pillows) read as slabs: replace them over each mattress with a draped duvet + foot throw + soft pillows / cushions (real_assets.soft / drape)."""
    ra = _ra(); n = rm = sp = 0; BED = ("BlanketFactory", "ComforterFactory", "BoxComforterFactory", "PillowFactory")
    for r, (lo, hi, t) in _rooms().items():
        if t != "bedroom":
            continue
        u = st[_unit(STY, (lo[0] + hi[0]) / 2)]
        if "duvet" not in u:
            continue
        mats = [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith("MattressFactory") and lo[0] < (_bb(o)[0][0] + _bb(o)[1][0]) / 2 < hi[0] and lo[1] < (_bb(o)[0][1] + _bb(o)[1][1]) / 2 < hi[1]]
        if not mats:                                                       # a room whose layout bed was refused: the real ABO spare bed is dressed like any other (duvet, throw, pillows, cushions)
            sb = bpy.data.objects.get(f"apt_SpareBed({r})")
            if sb is None and _spare_bed(r, lo, hi, n):
                n += 1; sp += 1; sb = bpy.data.objects.get(f"apt_SpareBed({r})")
            if sb is not None:
                mats = [sb]
        for mt in mats:
            m0, m1 = _bb(mt); ax = (m1[0] - m0[0]) >= (m1[1] - m0[1]); cx, cy = (m0[0] + m1[0]) / 2, (m0[1] + m1[1]) / 2; zt = _spare_top(mt, lo) if mt.name.startswith("apt_SpareBed") else m1[2]
            if st.get("mattress_white") and mt.data.materials and not mt.get("apt_mat_white") and not mt.name.startswith("apt_SpareBed"):              # P8 r9: the ABO bed's knit mattress was green and showed below the duvet: a white ticking mattress
                mt.data = mt.data.copy(); mw = _flat("ir_apt_mattress_white", (0.92, 0.91, 0.88), 0.9)
                for i_ in range(len(mt.data.materials)):
                    mt.data.materials[i_] = mw
                mt["apt_mat_white"] = 1
            for o in list(bpy.data.objects):
                if o.type == "MESH" and o.name.startswith(BED + (("TowelFactory",) if u.get("woven") else ())):      # P8 r7: a lived-in Infinigen towel lying across the foot read as a brown strap
                    a, b = _bb(o)
                    if m0[0] - 0.8 < (a[0] + b[0]) / 2 < m1[0] + 0.8 and m0[1] - 0.8 < (a[1] + b[1]) / 2 < m1[1] + 0.8 and zt - 0.9 < (a[2] + b[2]) / 2 < zt + 0.7:      # 0.8 m margin: the loose throw / bench blanket lying beside the bed
                        bpy.data.objects.remove(o, do_unlink=True); rm += 1
            hd = (1 if (cx - lo[0]) > (hi[0] - cx) else -1) if ax else (1 if (cy - lo[1]) > (hi[1] - cy) else -1)       # the head end is the one nearest its wall
            _LEAN[0] = (float(hd), 0.0) if ax else (0.0, float(hd))
            L, W = ((m1[0] - m0[0]), (m1[1] - m0[1])) if ax else ((m1[1] - m0[1]), (m1[0] - m0[0]))
            def at(a_, b_):
                return (cx + hd * a_, cy + b_) if ax else (cx + b_, cy + hd * a_)
            duv = _stripe_mat() if u["duvet"] == "stripe" else _flat(f"ir_apt_duvet_{int(u['duvet'][0] * 100)}", u["duvet"], 0.9)
            thr = _stripe_mat() if u["throw"] == "stripe" else _woven_mat(f"ir_apt_throw_w_{int(u['throw'][0] * 100)}_{int(u['throw'][1] * 100)}", u["throw"]) if u.get("woven") else _flat(f"ir_apt_throw_{int(u['throw'][0] * 100)}_{int(u['throw'][1] * 100)}", u["throw"], 0.9)
            pil = _flat("ir_apt_pillow", (0.95, 0.94, 0.9), 0.9); cus = _flat(f"ir_apt_cushion_{int(u['cushion'][0] * 100)}", u["cushion"], 0.9)
            c1 = at(-0.12, 0); dl = L - st.get("duvet_trim", 0.55)
            x0, x1 = (c1[0] - dl / 2, c1[0] + dl / 2) if ax else (c1[0] - W / 2, c1[0] + W / 2); y0, y1 = (c1[1] - W / 2, c1[1] + W / 2) if ax else (c1[1] - dl / 2, c1[1] + dl / 2)
            ra.drape(f"apt_Duvet({r})", duv, x0, x1, y0, y1, zt + 0.03, st.get("duvet_drop", 0.3), ax, thick=0.06, seed=n)
            tc = at(-L / 2 + 0.45, 0)
            tx0, tx1 = (tc[0] - 0.28, tc[0] + 0.28) if ax else (tc[0] - W / 2 - 0.02, tc[0] + W / 2 + 0.02); ty0, ty1 = (tc[1] - W / 2 - 0.02, tc[1] + W / 2 + 0.02) if ax else (tc[1] - 0.28, tc[1] + 0.28)
            _cf(ra.drape(f"apt_Throw({r})", thr, tx0, tx1, ty0, ty1, zt + 0.09, 0.27 if st.get("cloth_soft") else 0.34, ax, thick=0.014 if st.get("cloth_soft") else 0.025, seed=n + 5), st, ax, zt + 0.09, W, r, lo, hi, cx, cy)
            for k, bb_ in enumerate((-W / 4, W / 4)):
                pc = at(L / 2 - 0.4, bb_); _d, _h = _dims(st, "pillow", ax); _softp(st)(f"apt_Pillow({r}|{k})", pil, pc[0], pc[1], zt + 0.1, *_d, 0.14 * _h, seed=k + n, puff=0.6)
            for k, bb_ in enumerate((-0.2, 0.2)):
                pc = at(L / 2 - 0.64, bb_); _d, _h = _dims(st, "cushion", ax); _softp(st)(f"apt_Cushion({r}|{k})", cus, pc[0], pc[1], zt + 0.18, *_d, 0.3 * _h, yaw=0.12 * (1 if k else -1), seed=9 + k, puff=0.6)
            n += 1
    stats["apt_bedding"] = {"beds": n, "removed": rm, "spare_beds": sp}


def _rug_pick(rx, seed, x, y, z, yaw, fit):
    """An ABO rug whose name matches `rx` (no runner / shag / loud pattern); falls back to any big rug, recoloured by the caller."""
    import re
    import abo_assets
    ra = _ra()
    pool = [e for e in abo_assets.entries() if e.get("product_type") == "RUG" and re.search(rx, e.get("name", ""), re.I)
            and not re.search(r"runner|shag|floral|medallion|damask|moroccan|trellis|vintage|plaid|ornate|kilim|tribal|persian|oriental|round|circle", e.get("name", ""), re.I)
            and max(e.get("extent_m", (0, 0, 0))[:3]) >= 1.6]
    if pool:
        try:
            e = abo_assets.pick(random.Random(seed), pool); o = abo_assets._import(e, f"Real_rug({e['id']})")
            return ra._stand(o, x, y, z, yaw - math.atan2(ra.ABO_FRONT[1], ra.ABO_FRONT[0]), fit, grow=True)
        except Exception:                                           # noqa: BLE001
            pass
    return ra.abo("bigrug", seed, x, y, z, yaw, fit=fit)


def _beds():
    """[(room, lo, hi, cx, cy, ax, hd, L, W, ztop)] for every bedroom bed: a MattressFactory, or the spare bed's bbox."""
    out = []
    for r, (lo, hi, t) in _rooms().items():
        if t != "bedroom":
            continue
        found = False
        for o in bpy.data.objects:
            if o.type == "MESH" and o.name.startswith("MattressFactory"):
                m0, m1 = _bb(o)
                if lo[0] < (m0[0] + m1[0]) / 2 < hi[0] and lo[1] < (m0[1] + m1[1]) / 2 < hi[1]:
                    ax = (m1[0] - m0[0]) >= (m1[1] - m0[1]); cx, cy = (m0[0] + m1[0]) / 2, (m0[1] + m1[1]) / 2
                    hd = (1 if (cx - lo[0]) > (hi[0] - cx) else -1) if ax else (1 if (cy - lo[1]) > (hi[1] - cy) else -1)
                    L, W = ((m1[0] - m0[0]), (m1[1] - m0[1])) if ax else ((m1[1] - m0[1]), (m1[0] - m0[0]))
                    out.append((r, lo, hi, cx, cy, ax, hd, L, W, m1[2])); found = True
        if not found:
            for o in bpy.data.objects:
                if o.type == "MESH" and o.name.startswith(f"apt_SpareBed({r})"):
                    m0, m1 = _bb(o); ax = (m1[0] - m0[0]) >= (m1[1] - m0[1]); cx, cy = (m0[0] + m1[0]) / 2, (m0[1] + m1[1]) / 2
                    hd = (1 if (cx - lo[0]) > (hi[0] - cx) else -1) if ax else (1 if (cy - lo[1]) > (hi[1] - cy) else -1)
                    L, W = ((m1[0] - m0[0]), (m1[1] - m0[1])) if ax else ((m1[1] - m0[1]), (m1[0] - m0[0]))
                    out.append((r, lo, hi, cx, cy, ax, hd, L, W, _spare_top(o, lo)))
    return out


def _rugs(st, stats):
    """P8 r6: rugs under every bed (long side along the bed, ~1.2 m past the foot) and in each living room, ABO woven rugs by unit palette."""
    n = 0
    for (r, lo, hi, cx, cy, ax, hd, L, W, zt) in _beds():
        u = st[_unit(STY, (lo[0] + hi[0]) / 2)]
        if not (u.get("bedrugrx") or u.get("rugrx")):
            continue
        fo = u.get("rug_foot") if u.get("rug_foot") else st.get("rug_foot", 0.8); c = (cx - hd * fo, cy) if ax else (cx, cy - hd * fo); rl, rw = 3.0, 2.2
        sx, sy = (rl, rw) if ax else (rw, rl); sx = min(sx, hi[0] - lo[0] - 0.3); sy = min(sy, hi[1] - lo[1] - 0.3)
        rg = None
        for t in range(8):
            rg = _rug_pick(u.get("bedrugrx") or u["rugrx"], 61 + n + 11 * t, c[0], c[1], lo[2], 0.0 if ax else math.pi / 2, (sx, sy, 0.05) if ax else (sy, sx, 0.05))
            if rg is None:
                break
            bpy.context.view_layer.update(); r0, r1 = _bb(rg)
            if min(r1[0] - r0[0], r1[1] - r0[1]) >= 1.4 or t == 7:
                break
            bpy.data.objects.remove(rg, do_unlink=True); rg = None
        if rg is not None:
            bpy.context.view_layer.update(); r0, r1 = _bb(rg)
            if ((r1[0] - r0[0]) > (r1[1] - r0[1])) != (sx > sy):
                rg.rotation_euler[2] += math.pi / 2; bpy.context.view_layer.update(); r0, r1 = _bb(rg)
            rg.location.x += c[0] - (r0[0] + r1[0]) / 2; rg.location.y += c[1] - (r0[1] + r1[1]) / 2; rg.location.z += lo[2] + 0.003 - r0[2]
            bpy.context.view_layer.update(); r0, r1 = _bb(rg)                    # r8: keep the rug inside the room box (0-1's rug stuck 0.36 m through the wall)
            for ai, (l_, h_) in enumerate(((lo[0] + 0.12, hi[0] - 0.12), (lo[1] + 0.12, hi[1] - 0.12))):
                if r0[ai] < l_:
                    rg.location[ai] += l_ - r0[ai]
                elif r1[ai] > h_:
                    rg.location[ai] -= r1[ai] - h_
            rg.name = f"apt_BedRug({r})"; n += 1
    for r, (lo, hi, t) in _rooms().items():
        if t != "living-room":
            continue
        u = st[_unit(STY, (lo[0] + hi[0]) / 2)]
        if not u.get("rugrx"):
            continue
        w, d = hi[0] - lo[0], hi[1] - lo[1]; sx, sy = min(2.6, w - 1.0), min(1.9, d - 0.9)
        c = ((lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2)
        rg = _rug_pick(u["rugrx"], 91 + n, c[0], c[1], lo[2], 0.0, (sx, sy, 0.05))
        if rg is not None:
            bpy.context.view_layer.update(); r0, r1 = _bb(rg)
            rg.location.x += c[0] - (r0[0] + r1[0]) / 2; rg.location.y += c[1] - (r0[1] + r1[1]) / 2; rg.location.z += lo[2] + 0.003 - r0[2]
            rg.name = f"apt_LivRug({r})"; n += 1
    stats["apt_rugs"] = n


def _glow_shade(o, strength=6.0, split=False):
    """Shade-only emission (policy: real fixture): the lamp mesh's brightest large slot becomes a warm emissive shade."""
    if o is None or o.type != "MESH" or not o.data.materials:
        return 0
    area = {}
    for p in o.data.polygons:
        area[p.material_index] = area.get(p.material_index, 0.0) + p.area
    best = None
    for i, m in enumerate(o.data.materials):
        if m is None or not m.use_nodes:
            continue
        b = m.node_tree.nodes.get("Principled BSDF")
        if b is None:
            continue
        c = b.inputs["Base Color"].default_value; lum = 0.3 * c[0] + 0.59 * c[1] + 0.11 * c[2]
        sc_ = area.get(i, 0.0) * (1.0 if lum > 0.45 else 0.2)
        if best is None or sc_ > best[0]:
            best = (sc_, i, m)
    if best is None or best[0] <= 0:
        return 0
    o.data = o.data.copy(); m2 = best[2].copy(); b = m2.node_tree.nodes["Principled BSDF"]
    b.inputs["Emission Color"].default_value = (1.0, 0.82, 0.58, 1.0); b.inputs["Emission Strength"].default_value = strength
    m2["weathered"] = True
    if split:                                                          # P8 r9: the whole lamp is ONE slot, so the stem and base glowed white-hot too: only the upper faces (the shade) get the emissive copy
        me = o.data; zs = [v.co.z for v in me.vertices]; z0, z1 = min(zs), max(zs); cut = z0 + 0.5 * (z1 - z0)
        b.inputs["Base Color"].default_value = (1.0, 0.92, 0.78, 1.0)
        me.materials.append(m2); ni = len(me.materials) - 1
        for p_ in me.polygons:
            if p_.material_index == best[1] and sum(me.vertices[v].co.z for v in p_.vertices) / len(p_.vertices) > cut:
                p_.material_index = ni
        return 1
    o.data.materials[best[1]] = m2
    return 1


def _bedside(st, stats):
    """P8 r6: a nightstand + a real table lamp (ABO LAMP, warm point light in the shade) on each side of every bed; existing layout nightstands are reused."""
    ra = _ra(); n = ln = ns_new = 0
    for (r, lo, hi, cx, cy, ax, hd, L, W, zt) in _beds():
        u = st[_unit(STY, (lo[0] + hi[0]) / 2)]
        if not u.get("bedside"):
            continue
        stands = [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith(("AboNightstandFactory", "apt_Nightstand")) and lo[0] < (_bb(o)[0][0] + _bb(o)[1][0]) / 2 < hi[0] and lo[1] < (_bb(o)[0][1] + _bb(o)[1][1]) / 2 < hi[1]]
        for sgn in (-1, 1):
            hx = cx + hd * (L / 2 - 0.25) if ax else cx + sgn * (W / 2 + 0.27)
            hy = cy + sgn * (W / 2 + 0.27) if ax else cy + hd * (L / 2 - 0.25)
            near = [o for o in stands if abs((_bb(o)[0][0] + _bb(o)[1][0]) / 2 - hx) < 0.7 and abs((_bb(o)[0][1] + _bb(o)[1][1]) / 2 - hy) < 0.7]
            if near:
                a, b = _bb(near[0]); px, py, pz = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2, b[2]
            else:
                if not (lo[0] + 0.2 < hx < hi[0] - 0.2 and lo[1] + 0.2 < hy < hi[1] - 0.2):
                    continue
                clash = False
                for o in bpy.data.objects:
                    if o.type == "MESH" and not o.name.endswith(SKIP_OBJ) and not ("/" in o.name and "(" not in o.name and "." not in o.name) and not o.name.startswith(("apt_Downlights", "Baseboard", "apt_BedRug", "apt_LivRug", "apt_Duvet", "apt_Throw", "apt_Pillow", "apt_Cushion", "apt_Runner", "apt_Euro", "apt_Fold", "MattressFactory", "BedFactory", "apt_SpareBed", "window", "WindowFactory", "Curtain")):
                        a, b = _bb(o)
                        if b[2] > 0.25 and a[2] < 1.5 and abs((a[0] + b[0]) / 2 - hx) < (b[0] - a[0]) / 2 + 0.22 and abs((a[1] + b[1]) / 2 - hy) < (b[1] - a[1]) / 2 + 0.22:
                            clash = True; break
                if clash:
                    continue
                ns = ra.abo("sidetable", 71 + n, hx, hy, lo[2], 0.0, fit=(0.5, 0.45, 0.58))
                if ns is None:
                    continue
                ns.name = f"apt_Nightstand({r}|{sgn})"; bpy.context.view_layer.update(); a, b = _bb(ns); px, py, pz = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2, b[2]; ns_new += 1
            lamp = ra.abo("tablelamp", 81 + n, px, py, pz, 0.0, fit=(0.3, 0.3, 0.5))
            n += 1
            if lamp is None:
                continue
            lamp.name = f"apt_BedLamp({r}|{sgn})"; bpy.context.view_layer.update(); a, b = _bb(lamp)
            if st.get("glow_shades"):
                stats["apt_shades_glow"] = stats.get("apt_shades_glow", 0) + _glow_shade(lamp, st.get("shade_emit", 6.0), st.get("shade_split", False))
            _light(f"ir_apt_bedlamp_{r}_{sgn}", "POINT", ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, b[2] - 0.12), 30.0, (1.0, 0.78, 0.5), r=0.08); ln += 1
            if st.get("lamp_wash"):                                       # r8: a visible warm pool on the wall behind the lamp (spot from the shade toward the bed's head wall)
                from mathutils import Vector as _V
                sp = _light(f"ir_apt_lampwash_{r}_{sgn}", "SPOT", ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, b[2] - 0.2), 55.0, (1.0, 0.74, 0.46))
                sp.data.spot_size = math.radians(65); sp.data.spot_blend = 0.8
                d = _V((hd, 0.0, -0.18)) if ax else _V((0.0, hd, -0.18))
                sp.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    stats["apt_bedside"] = {"lamps": ln, "new_nightstands": ns_new}


def _bedding_layers(st, stats):
    """P8 r6: layered bedding on top of the plain duvet / throw / cushions: 2 euro pillows behind the sleeping pillows, a folded-back duvet cuff at the head, a contrast runner across the foot."""
    ra = _ra(); n = 0
    for (r, lo, hi, cx, cy, ax, hd, L, W, zt) in _beds():
        u = st[_unit(STY, (lo[0] + hi[0]) / 2)]
        if not u.get("layers"):
            continue
        _LEAN[0] = (float(hd), 0.0) if ax else (0.0, float(hd))
        def at(a_, b_):
            return (cx + hd * a_, cy + b_) if ax else (cx + b_, cy + hd * a_)
        eu = _flat(f"ir_apt_euro_{int(u['euro'][0] * 100)}", u["euro"], 0.9); run = _woven_mat(f"ir_apt_runner_w_{int(u['runner'][0] * 100)}_{int(u['runner'][2] * 100)}", u["runner"], 0.06) if u.get("woven") else _flat(f"ir_apt_runner_{int(u['runner'][0] * 100)}_{int(u['runner'][2] * 100)}", u["runner"], 0.9)
        dvr = u["duvet"] if not isinstance(u["duvet"], str) else (0.9, 0.9, 0.88); cuff = _flat(f"ir_apt_cuff_{int(dvr[0] * 100)}", tuple(max(0.0, c - 0.06) for c in dvr), 0.9)
        for k, bb_ in enumerate((-W / 4, W / 4)):
            pc = at(L / 2 - 0.27, bb_); _d, _h = _dims(st, "euro", ax); _softp(st)(f"apt_Euro({r}|{k})", eu, pc[0], pc[1], zt + 0.3, *_d, (0.4 if STY.get("pillow_xy") else 0.5) * _h, yaw=0.0, seed=21 + k, puff=0.7)
        cc = at(L / 2 - 0.62, 0); x0, x1 = (cc[0] - 0.17, cc[0] + 0.17) if ax else (cc[0] - W / 2 - 0.02, cc[0] + W / 2 + 0.02); y0, y1 = (cc[1] - W / 2 - 0.02, cc[1] + W / 2 + 0.02) if ax else (cc[1] - 0.17, cc[1] + 0.17)
        (_roll_fold(f"apt_Fold({r})", cuff, cc, ax, W, zt, r, lo, hi) if st.get("cloth_soft") else ra.drape(f"apt_Fold({r})", cuff, x0, x1, y0, y1, zt + 0.1, 0.28, ax, thick=0.05, seed=n + 33))
        rh = 0.25 if u.get("woven") else 0.17                              # P8 r7: a 0.5 m wide soft runner (was a 0.34 m strap that read as a belt)
        rc = at(-L / 2 + 0.95, 0); x0, x1 = (rc[0] - rh, rc[0] + rh) if ax else (rc[0] - W / 2 - 0.02, rc[0] + W / 2 + 0.02); y0, y1 = (rc[1] - W / 2 - 0.02, rc[1] + W / 2 + 0.02) if ax else (rc[1] - rh, rc[1] + rh)
        _cf(ra.drape(f"apt_Runner({r})", run, x0, x1, y0, y1, zt + (0.085 if u.get("woven") else 0.07), 0.25 if st.get("cloth_soft") else 0.3, ax, thick=0.014 if st.get("cloth_soft") else (0.035 if u.get("woven") else 0.02), seed=n + 45), st, ax, zt + (0.085 if u.get("woven") else 0.07), W, r, lo, hi, cx, cy)
        n += 1
    stats["apt_layers"] = n


def _baths(st, stats):
    ra = _ra(); n = m = g = 0
    for r, (lo, hi, t) in _rooms().items():
        if t != "bathroom":
            continue
        u = st[_unit(STY, (lo[0] + hi[0]) / 2)]; slate = u["bath"] == "slate"
        bpy.context.view_layer.update()
        for o in list(bpy.data.objects):
            if o.type != "MESH":
                continue
            a, b = _bb(o)
            if not (lo[0] < (a[0] + b[0]) / 2 < hi[0] and lo[1] < (a[1] + b[1]) / 2 < hi[1]):
                continue
            if o.name.startswith("HomeVanityFactory"):
                vc = u.get("vanity")
                _recolour(o, vc if vc else (0.3, 0.19, 0.11) if slate else (0.94, 0.94, 0.92), "ir_apt_vanity_oak" if vc else "ir_apt_vanity_wal" if slate else "ir_apt_vanity_white", 0.4); n += 1
                if u.get("mirror"):
                    _round_mirror_and_rug(r, lo, hi, a, b)
                fx = ra.hssd(r"mixer|basin mixer|faucet|tap", 3 + n, (a[0] + b[0]) / 2, (a[1] + b[1]) / 2, b[2], 0.0, fit=(0.18, 0.22, 0.28), size=(0.1, 0.45))
                if fx is not None:
                    _recolour(fx, (0.05, 0.05, 0.05) if slate else (0.72, 0.52, 0.22), "ir_apt_tap_black" if slate else "ir_apt_tap_brass", 0.25); m += 1
            elif o.name.startswith("WashBasinFactory") and u.get("vanity") and not any(q.name.startswith(("HomeVanityFactory", "apt_Vanity")) for q in bpy.data.objects if q.type == "MESH" and lo[0] < (_bb(q)[0][0] + _bb(q)[1][0]) / 2 < hi[0] and lo[1] < (_bb(q)[0][1] + _bb(q)[1][1]) / 2 < hi[1]):
                if _oak_vanity_for_basin(r, lo, hi, u, o, n):
                    n += 1
            elif o.name.startswith("ShowerEnclosureFactory"):
                gl = _flat("ir_apt_shower_glass", (0.85, 0.9, 0.92), 0.03); b2 = gl.node_tree.nodes["Principled BSDF"]
                if "Transmission Weight" in b2.inputs:
                    b2.inputs["Transmission Weight"].default_value = 0.92
                o.data = o.data.copy()
                for i, sl in enumerate(o.data.materials):
                    if sl is not None and ("glass" in sl.name.lower() or "transl" in sl.name.lower() or "frost" in sl.name.lower()):
                        o.data.materials[i] = gl
                g += 1
        if not any(o.type == "MESH" and o.name.startswith("ShowerEnclosureFactory") and lo[0] < (_bb(o)[0][0] + _bb(o)[1][0]) / 2 < hi[0] and lo[1] < (_bb(o)[0][1] + _bb(o)[1][1]) / 2 < hi[1] for o in bpy.data.objects):
            g += _shower(r, lo, hi, slate)                           # r4: the layout carried no shower: build a glass enclosure in the freest corner
    stats["apt_baths"] = {"vanities": n, "taps": m, "showers": g}


def _float_vanity(r, vo):
    """P7 r5 (REF: floating oak vanity): lift 0.25 m, dark recessed gap strip underneath (a plain dark kick-plate box inset 6 cm from the vanity footprint)."""
    from room_planner import proc_boutique_flagship as fl
    bpy.context.view_layer.update(); mw = vo.matrix_world; z0 = min((mw @ v.co).z for v in vo.data.vertices); tot = low = 0.0
    for p_ in vo.data.polygons:
        tot += p_.area; low += p_.area if (mw @ p_.center).z < z0 + 0.25 else 0.0
    if tot <= 0 or low / tot < 0.10:                                     # an open stand (legs only): lifting it would leave the legs hanging
        return _wall_vanity(r, vo)                                       # P7 r6: replace the stand by a floating wall vanity
    vo.location.z += 0.25; bpy.context.view_layer.update(); va, vb = _bb(vo)
    gap = _flat("ir_apt_vanity_gap", (0.025, 0.022, 0.02), 0.9)
    fl.mesh_object(f"apt_VanityGap({r})", [(gap, [("box", (va[0] + vb[0]) / 2, (va[1] + vb[1]) / 2, va[2] - 0.125, max(0.1, vb[0] - va[0] - 0.12), max(0.1, vb[1] - va[1] - 0.12), 0.25)])], bevel=False)


def _wall_vanity(r, vo):
    """P7 r6: an open legged stand cannot float: remove it and build a wall-hung oak vanity on its footprint (bottom 0.4 m up, two drawers, stone top, a white vessel basin, the old tap stays above). Returns True."""
    from room_planner import proc_boutique_flagship as fl
    bpy.context.view_layer.update(); va, vb = _bb(vo); cx, cy = (va[0] + vb[0]) / 2, (va[1] + vb[1]) / 2; along_x = (vb[0] - va[0]) >= (vb[1] - va[1])
    L = max(vb[0] - va[0], vb[1] - va[1], 0.8); D = min(max(min(vb[0] - va[0], vb[1] - va[1]), 0.42), 0.55); z0 = va[2] + 0.4; zt = va[2] + 0.86
    mats = [m for m in vo.data.materials if m is not None]; oak = next((m for m in mats if m.name.startswith("ir_apt_vanity")), None) or _flat("ir_apt_vanity_oak", (0.7, 0.52, 0.32), 0.4)
    stone = _flat("ir_apt_vanity_top", (0.86, 0.84, 0.8), 0.3); dark = _flat("ir_apt_vanity_gap", (0.025, 0.022, 0.02), 0.9); bas = _flat("ir_apt_basin_white", (0.95, 0.95, 0.94), 0.12); brass = _flat("ir_apt_vanity_pull", (0.72, 0.52, 0.22), 0.3, 1.0)
    def bx(c0, c1, d0, d1, za, zb):                                    # along-wall coord, depth from the wall-facing side (centre-based)
        if along_x:
            return ("box", cx + (c0 + c1) / 2, cy + (d0 + d1) / 2, (za + zb) / 2, c1 - c0, d1 - d0, zb - za)
        return ("box", cx + (d0 + d1) / 2, cy + (c0 + c1) / 2, (za + zb) / 2, d1 - d0, c1 - c0, zb - za)
    hl, hd = L / 2, D / 2
    body = [bx(-hl, hl, -hd, hd - 0.025, z0, zt - 0.03)]
    fronts = [bx(-hl + 0.01, -0.005, hd - 0.03, hd, z0 + 0.02, zt - 0.05), bx(0.005, hl - 0.01, hd - 0.03, hd, z0 + 0.02, zt - 0.05)]
    top = [bx(-hl - 0.01, hl + 0.01, -hd, hd + 0.02, zt - 0.03, zt)]
    bowl = [bx(-0.2, 0.2, -0.17, 0.17, zt, zt + 0.1)]
    pulls = []
    for sgn in (-1, 1):
        a = bx(sgn * hl / 2 - 0.1, sgn * hl / 2 + 0.1, hd, hd + 0.03, z0 + 0.24, z0 + 0.255)
        pulls.append(a)
    gap = [bx(-hl + 0.05, hl - 0.05, -hd + 0.04, hd - 0.04, z0 - 0.02, z0)]
    fl.mesh_object(f"apt_WallVanity({r})", [(oak, body + fronts), (stone, top), (bas, bowl), (brass, pulls), (dark, gap)], bevel=True)
    bpy.data.objects.remove(vo, do_unlink=True)
    nv = bpy.data.objects.get(f"apt_WallVanity({r})")
    if nv is not None:
        nv.name = f"apt_Vanity({r})"
    return True


def _oak_vanity_for_basin(r, lo, hi, u, bsn, n):
    """P7: the layout carries a WashBasinFactory, not a HomeVanity, so the oak vanity / round mirror never appeared. Replace the basin by an HSSD vanity against its nearest wall, oak, and hang the round mirror above it. Returns True when done."""
    import wall_face
    ra = _ra(); a, b = _bb(bsn); cx, cy = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
    d = {"W": cx - lo[0], "E": hi[0] - cx, "S": cy - lo[1], "N": hi[1] - cy}; w = min(d, key=d.get); ins = wall_face.inset(r, w, 0.11); depth = 0.5
    x, y, yaw = {"S": (cx, lo[1] + ins + depth / 2, math.pi / 2), "N": (cx, hi[1] - ins - depth / 2, -math.pi / 2), "W": (lo[0] + ins + depth / 2, cy, 0.0), "E": (hi[0] - ins - depth / 2, cy, math.pi)}[w]
    vo = None
    for k in range(10):                                           # a model pick can be a flat shelf or a tall cabinet: redraw until it stands 0.65-1.05 m tall and at least 0.3 m deep once fitted
        vo = ra.hssd(r"vanity|sink cabinet|bathroom cabinet|wash ?basin cabinet", 41 + n + 7 * k, x, y, lo[2], yaw, fit=(0.9, depth, 0.85), size=(0.6, 1.8), grow=True)
        if vo is None:
            return False
        bpy.context.view_layer.update(); va, vb = _bb(vo)
        if 0.65 <= vb[2] - va[2] <= 1.05 and min(vb[0] - va[0], vb[1] - va[1]) >= 0.3:
            break
        bpy.data.objects.remove(vo, do_unlink=True); vo = None
    if vo is None:
        return False
    bpy.data.objects.remove(bsn, do_unlink=True)
    _recolour(vo, u["vanity"], "ir_apt_vanity_oak", 0.4); vo.name = f"apt_Vanity({r})"
    bpy.context.view_layer.update()
    if STY.get("floating_vanity"):
        _float_vanity(r, vo)
        vo = bpy.data.objects.get(f"apt_Vanity({r})") or vo
    bpy.context.view_layer.update(); va, vb = _bb(vo)
    _round_mirror_and_rug(r, lo, hi, va, vb)
    return True


def _round_mirror_and_rug(r, lo, hi, a, b):
    """p7 baths: a round mirror in a thin oak ring on the wall behind the vanity + a small woven rug in front (the vanity's back is the nearest room wall)."""
    from room_planner import proc_boutique_flagship as fl
    cx, cy = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
    d = {"W": cx - lo[0], "E": hi[0] - cx, "S": cy - lo[1], "N": hi[1] - cy}; w = min(d, key=d.get)
    mir = _flat("ir_apt_mirror", (0.9, 0.92, 0.95), 0.02, 1.0); ring = _flat("ir_apt_mirror_ring", (0.7, 0.52, 0.32), 0.4); z = b[2] + 0.75
    e = 0.02; face = {"W": (lo[0] + e, cy, 1, 0), "E": (hi[0] - e, cy, -1, 0), "S": (cx, lo[1] + e, 0, 1), "N": (cx, hi[1] - e, 0, -1)}[w]
    wx, wy, nx, ny = face
    led = _emit("ir_apt_mirror_led", (1.0, 0.86, 0.66), 5.0)
    if STY.get("backlit_mirror") and not STY.get("rect_mirror"):            # p9 REF: a mirror with an LED halo (a real fixture): the emissive ring sits just behind the glass
        fl.mesh_object(f"apt_MirrorLED({r})", [(led, [("cyl", (wx + nx * 0.004, wy + ny * 0.004, z), (wx + nx * 0.009, wy + ny * 0.009, z), 0.385, 48)])], bevel=False)
        ring = _flat("ir_apt_mirror_ring", (0.7, 0.52, 0.32), 0.4)
    if STY.get("rect_mirror"):                                              # r2: the p7 / p9 references show a large rectangular mirror, not a round one
        mw = max(0.7, min(1.3, ((b[0] - a[0]) if nx == 0 else (b[1] - a[1])) * 0.95)); mh = 0.78
        def bx(w_, h_, t_, off):
            return ("box", wx + nx * off, wy + ny * off, z, (t_ if nx else w_), (w_ if nx else t_), h_)
        if STY.get("backlit_mirror"):
            fl.mesh_object(f"apt_MirrorLED({r})", [(led, [bx(mw + 0.1, mh + 0.1, 0.006, 0.004)])], bevel=False)
        fl.mesh_object(f"apt_Mirror({r})", [(ring, [bx(mw + 0.04, mh + 0.04, 0.02, 0.01)]), (mir, [bx(mw, mh, 0.012, 0.02)])], bevel=False)
    else:
        for rad, mt, dz in ((0.36, ring, 0.0), (0.33, mir, 0.006)):
            fl.mesh_object(f"apt_RoundMirror({r}|{int(rad*100)})", [(mt, [("cyl", (wx + nx * dz, wy + ny * dz, z), (wx + nx * (dz + 0.012), wy + ny * (dz + 0.012), z), rad, 40)])], bevel=False)
    rug = _flat("ir_apt_bathrug", (0.86, 0.8, 0.7), 0.95)
    _ra().soft(f"apt_BathRug({r})", rug, cx + nx * 0.55, cy + ny * 0.55, lo[2], 0.8 if nx == 0 else 0.5, 0.5 if nx == 0 else 0.8, 0.03, yaw=0.0, seed=3, puff=0.1)


def _shower(r, lo, hi, slate):
    from room_planner import proc_boutique_flagship as fl
    sp = _free_patch(lo, hi, _obstacles(lo, hi), 0.95, 0.95, margin=0.02)
    if sp is None:
        return 0
    x, y = sp; z0 = lo[2]; W = 0.9
    ex = -1 if (x - lo[0]) < (hi[0] - x) else 1; ey = -1 if (y - lo[1]) < (hi[1] - y) else 1          # the walls are on the (ex, ey) side; glass goes on the open sides
    gl = _flat("ir_apt_shower_glass", (0.85, 0.9, 0.92), 0.03); b2 = gl.node_tree.nodes["Principled BSDF"]
    if "Transmission Weight" in b2.inputs:
        b2.inputs["Transmission Weight"].default_value = 0.92
    chrome = _flat("ir_apt_chrome", (0.8, 0.8, 0.82), 0.12, 1.0); tray = _flat("ir_apt_tray", (0.2, 0.2, 0.21) if slate else (0.92, 0.92, 0.9), 0.4)
    gp = [("box", x - ex * W / 2, y, z0 + 1.0, 0.012, W, 2.0), ("box", x, y - ey * W / 2, z0 + 1.0, W, 0.012, 2.0)]
    fp = [("cyl", (x - ex * W / 2, y - ey * W / 2, z0), (x - ex * W / 2, y - ey * W / 2, z0 + 2.0), 0.012, 8), ("cyl", (x - ex * W / 2, y + ey * W / 2, z0), (x - ex * W / 2, y + ey * W / 2, z0 + 2.0), 0.012, 8),
          ("cyl", (x + ex * W / 2, y - ey * W / 2, z0), (x + ex * W / 2, y - ey * W / 2, z0 + 2.0), 0.012, 8),
          ("cyl", (x + ex * W / 2, y + ey * W / 2 * 0.0 + ey * W / 2, z0 + 2.0), (x + ex * W / 2 + ex * 0.0, y + ey * W / 2, z0 + 2.0), 0.001, 4),
          ("cyl", (x + ex * W / 2 - ex * 0.25, y + ey * W / 2 - ey * 0.1, z0 + 2.1), (x + ex * W / 2 - ex * 0.25, y + ey * W / 2 - ey * 0.1, z0 + 2.12), 0.13, 24),
          ("cyl", (x + ex * W / 2 - ex * 0.02, y + ey * W / 2 - ey * 0.1, z0 + 2.11), (x + ex * W / 2 - ex * 0.25, y + ey * W / 2 - ey * 0.1, z0 + 2.11), 0.01, 8)]
    fl.mesh_object(f"apt_Shower({r})", [(gl, gp), (chrome, fp), (tray, [("box", x, y, z0 + 0.025, W, W, 0.05)])], bevel=False)
    return 1


def _globe(name, x, y, z, mat, r=0.14):
    import bmesh
    bm = bmesh.new(); bmesh.ops.create_uvsphere(bm, u_segments=32, v_segments=20, radius=r)
    for f in bm.faces:
        f.smooth = True
    bmesh.ops.translate(bm, vec=(x, y, z), verts=bm.verts)
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free(); me.materials.append(mat)
    o = bpy.data.objects.new(name, me); bpy.context.scene.collection.objects.link(o)


def _dining(st, stats):
    ra = _ra(); n = 0
    from room_planner import proc_boutique_flagship as fl
    for r, (lo, hi, t) in _rooms().items():
        if t != "kitchen":
            continue
        u = st[_unit(STY, (lo[0] + hi[0]) / 2)]; bpy.context.view_layer.update(); obs = _obstacles(lo, hi)
        zc = _zc(r, lo); spot = None
        for ps in (1.9, 1.5, 1.2):                                   # r4: the layout's own table + island leave no 1.9 m patch: try smaller sets
            spot = _free_patch(lo, hi, obs, ps, ps)
            if spot is not None:
                break
        black = u["dining"] == "black_round"
        if u["dining"] == "nook":
            continue                                                       # p9: the craft / dining nook is built in _p9_nook (round walnut table + white swivel chairs)
        if spot is None:                                              # still nothing: dress the layout's own table (colour + pendant over it) instead of skipping
            tabs = [o for o in bpy.data.objects if o.type == "MESH" and ("Table" in o.name or "table" in o.name) and lo[0] < (_bb(o)[0][0] + _bb(o)[1][0]) / 2 < hi[0] and lo[1] < (_bb(o)[0][1] + _bb(o)[1][1]) / 2 < hi[1] and 0.55 < _bb(o)[1][2] - lo[2] < 1.0]
            if not tabs:
                continue
            tb0 = tabs[0]; b0_, b1_ = _bb(tb0); x, y = (b0_[0] + b1_[0]) / 2, (b0_[1] + b1_[1]) / 2
            _recolour(tb0, (0.04, 0.04, 0.045) if black else (0.95, 0.95, 0.93), "ir_apt_table_black" if black else "ir_apt_table_white", 0.35)
            stats["apt_dining_existing"] = stats.get("apt_dining_existing", 0) + 1
        else:
            x, y = spot
        tb = None if spot is None else ra.hssd(r"round dining table|dining table|round.*table", 21 + n, x, y, lo[2], 0.0, fit=(1.1 if black else 1.4, 1.1 if black else 0.9, 0.76), size=(0.7, 2.2))
        if tb is not None:
            _recolour(tb, (0.04, 0.04, 0.045) if black else (0.95, 0.95, 0.93), "ir_apt_table_black" if black else "ir_apt_table_white", 0.35)
        for k in range(4 if spot is not None else 0):
            a = math.pi / 2 * k + 0.4; cx, cy = x + 0.78 * math.cos(a), y + 0.78 * math.sin(a)
            ch = ra.abo("deskchair", 31 + k + n, cx, cy, lo[2], a + math.pi)
            if ch is not None:
                _recolour(ch, (0.92, 0.88, 0.8) if black else (0.95, 0.95, 0.93), "ir_apt_chair_cream" if black else "ir_apt_chair_white", 0.6)
        if u["pendant"] == "globe":
            smoke = _flat("ir_apt_smoke", (0.08, 0.075, 0.075), 0.05); b2 = smoke.node_tree.nodes["Principled BSDF"]
            if "Transmission Weight" in b2.inputs:
                b2.inputs["Transmission Weight"].default_value = 0.35
            for k in range(3):
                px = x + (k - 1) * 0.5; z = zc - 0.9 - 0.18 * (k % 2)
                fl.mesh_object(f"apt_Globe({r}_{k})", [(smoke, [("cyl", (px, y, zc), (px, y, z + 0.14), 0.004, 6)]), (_emit("ir_apt_globe_core", (1.0, 0.8, 0.55), 2.5), [("cyl", (px, y, z), (px, y, z + 0.001), 0.05, 12)])], bevel=False)
                _globe(f"apt_GlobeShell({r}_{k})", px, y, z, smoke)
                _light(f"ir_apt_globe_{r}_{k}", "POINT", (px, y, z), 30, (1.0, 0.78, 0.5), r=0.12)
        else:
            pd = ra.hssd(r"lantern|paper.*(pendant|lamp)|rice paper|rattan.*(pendant|lamp)" if u["pendant"] == "lantern" else r"pleat.*(drum|pendant)|drum pendant", 51 + n, x, y, zc - 0.62, 0.0, fit=(0.9, 0.9, 0.55), size=(0.5, 1.4), grow=True)
            _light(f"ir_apt_pleat_{r}", "POINT", (x, y, zc - 0.5), 55, (1.0, 0.82, 0.62), r=0.2)
        n += 1
    stats["apt_dining"] = n


def _feature(st, stats):
    """P7 r4: unit A's feature walls (REF: cream rooms with ONE brick-red wall behind the sofa / the bed head): a thin brick-red panel flush on the wall, clear of doors."""
    import wall_face
    from room_planner import proc_boutique_flagship as fl
    n = 0
    def panel(r, lo, hi, side, c, span, rgb):
        ins = wall_face.inset(r, side, 0.11); zc = _zc(r, lo); z0, z1 = lo[2] + 0.05, zc - 0.02
        along = (lo[0] + 0.25, hi[0] - 0.25) if side in "SN" else (lo[1] + 0.25, hi[1] - 0.25)
        a0 = max(along[0], c - span / 2); a1 = min(along[1], c + span / 2)
        if a1 - a0 < 1.2:
            return False
        for o in bpy.data.objects:                                         # doors on that wall: trim the panel away from them
            if o.type == "MESH" and o.name.startswith(DOORS):
                d0, d1 = _bb(o)
                on = (abs(d0[1] - (lo[1] if side == "S" else hi[1])) < 0.9 or abs(d1[1] - (lo[1] if side == "S" else hi[1])) < 0.9) if side in "SN" else (abs(d0[0] - (lo[0] if side == "W" else hi[0])) < 0.9 or abs(d1[0] - (lo[0] if side == "W" else hi[0])) < 0.9)
                if on:
                    q0, q1 = (d0[0] - 0.15, d1[0] + 0.15) if side in "SN" else (d0[1] - 0.15, d1[1] + 0.15)
                    if q0 < a1 and q1 > a0:
                        return False
        m = _flat(f"ir_apt_brickred_{int(rgb[0] * 100)}", rgb, 0.85)
        t = 0.03; mid = (a0 + a1) / 2; ln = a1 - a0; zm = (z0 + z1) / 2
        if side in "SN":
            y = (lo[1] + ins + t / 2 + 0.002) if side == "S" else (hi[1] - ins - t / 2 - 0.002); pr = ("box", mid, y, zm, ln, t, z1 - z0)
        else:
            x = (lo[0] + ins + t / 2 + 0.002) if side == "W" else (hi[0] - ins - t / 2 - 0.002); pr = ("box", x, mid, zm, t, ln, z1 - z0)
        fl.mesh_object(f"apt_FeatureWall({r}|{side})", [(m, [pr])], bevel=False)
        return True
    for r, (lo, hi, t) in _rooms().items():
        u = st[_unit(STY, (lo[0] + hi[0]) / 2)]
        if not u.get("feature") or t != "living-room":
            continue
        sofas = [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith(("AboSofaFactory", "LoveseatFactory")) and lo[0] < (_bb(o)[0][0] + _bb(o)[1][0]) / 2 < hi[0] and lo[1] < (_bb(o)[0][1] + _bb(o)[1][1]) / 2 < hi[1]]
        if sofas:
            a, b2 = _bb(sofas[0]); cx, cy = (a[0] + b2[0]) / 2, (a[1] + b2[1]) / 2; span = max(b2[0] - a[0], b2[1] - a[1]) + 1.6
        else:
            cx, cy = (lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2; span = 3.0
        sides = sorted("SNWE", key=lambda s_: {"S": cy - lo[1], "N": hi[1] - cy, "W": cx - lo[0], "E": hi[0] - cx}[s_])
        for s_ in sides:
            if panel(r, lo, hi, s_, cx if s_ in "SN" else cy, span, u["feature"]):
                n += 1; break
    for (r, lo, hi, cx, cy, ax, hd, L, W, zt) in _beds():
        u = st[_unit(STY, (lo[0] + hi[0]) / 2)]
        sd_ = ("E" if hd > 0 else "W") if ax else ("N" if hd > 0 else "S")
        if (u.get("feature") or u.get("bedfeature")) and (panel(r, lo, hi, sd_, cy if ax else cx, W + 1.8, u.get("feature") or u["bedfeature"]) or panel(r, lo, hi, sd_, cy if ax else cx, W + 0.5, u.get("feature") or u["bedfeature"])):   # P7 r8: retry narrower when a door/window casing sits near the wide span
            n += 1
    stats["apt_feature_walls"] = n


def _kitchen_run(st, u, r, lo, hi, side, alongx, a0, a1, ins, n):
    """P7 r6: a built continuous kitchen run on the wall segment a0..a1: toe kick, butted base doors (0.6 m, raised panels, bar handles), ONE worktop over the run with an overhang, a cooker module (steel oven door with a dark window, knobs, a 4-ring hob) beside the sink module (basin + the HSSD tap), a tile backsplash, upper cabinets 0.35 m deep at 1.4-2.1 m except over the cooker, and a hood (HSSD, else built). Returns the module count."""
    from room_planner import proc_boutique_flagship as fl
    ra = _ra(); front, top_c = u["kitchen"]; unit = _unit(STY, (lo[0] + hi[0]) / 2); zf = lo[2]; L = a1 - a0
    stone = unit in ("A", "C")
    fm = _flat(f"ir_apt_kfront_{int(front[0] * 100)}_{int(front[1] * 100)}", front, 0.45); pm = _flat(f"ir_apt_kpanel_{int(front[0] * 100)}_{int(front[1] * 100)}", tuple(min(1.0, c * 1.08) for c in front), 0.45)
    tm = _flat("ir_apt_ktop_stone", (0.86, 0.84, 0.8), 0.3) if stone else _flat("ir_apt_ktop_oak", (0.7, 0.52, 0.32), 0.4)
    car = _flat("ir_apt_kcarcass", (0.16, 0.14, 0.12), 0.7); kick = _flat("ir_apt_kkick", (0.04, 0.04, 0.045), 0.6); steel = _flat("ir_apt_ksteel", (0.76, 0.77, 0.79), 0.28, 1.0); glass = _flat("ir_apt_kovenglass", (0.03, 0.03, 0.035), 0.1)
    hob = _flat("ir_apt_khob", (0.02, 0.02, 0.022), 0.15); ring = _flat("ir_apt_khobring", (0.45, 0.45, 0.47), 0.3, 1.0); basin = _flat("ir_apt_kbasin", (0.55, 0.56, 0.58), 0.2, 1.0)
    sp_rgb = (0.85, 0.8, 0.7) if unit == "A" else (0.93, 0.93, 0.91) if unit == "B" else (0.65, 0.66, 0.68)
    spl = _tile(f"ir_apt_ksplash_{unit}", sp_rgb, 0.1, tuple(c * 0.75 for c in sp_rgb), 0.15, brick=True)
    def W(s_, d_, z_):
        return {"S": (a0 + s_, lo[1] + ins + d_, z_), "N": (a0 + s_, hi[1] - ins - d_, z_), "W": (lo[0] + ins + d_, a0 + s_, z_), "E": (hi[0] - ins - d_, a0 + s_, z_)}[side]
    def box(s0, s1, d0, d1, z0, z1):
        x, y, _ = W((s0 + s1) / 2, (d0 + d1) / 2, 0); sa, sd = s1 - s0, d1 - d0
        return ("box", x, y, zf + (z0 + z1) / 2, *((sa, sd) if alongx else (sd, sa)), z1 - z0)
    def bar(s0, s1, d, z_):
        p0 = W(s0, d, zf + z_); p1 = W(s1, d, zf + z_); return ("cyl", p0, p1, 0.008, 8)
    def knob(s_, d, z_):
        p0 = W(s_, d, zf + z_); p1 = W(s_, d + 0.03, zf + z_); return ("cyl", p0, p1, 0.015, 10)
    # module plan: [bases][sink][bases][cooker]
    ck = 0.6 if L >= 2.4 else 0.0; sk = 1.2 if L >= 3.0 else 0.9; rem = L - ck - sk; nb = max(0, int(round(rem / 0.6))); bw = rem / nb if nb else 0.0
    order = ["base"] * (nb // 2) + ["sink"] + ["base"] * (nb - nb // 2) + (["cooker"] if ck else [])
    wid = {"sink": sk, "cooker": ck, "base": bw}
    body = [box(0, L, 0, 0.56, 0.1, 0.86)]; toe = [box(0, L, 0.05, 0.58, 0, 0.1)]; doors = []; panels = []; bars = []; stl = []; glassp = []; knobs = []; hobs = []; rings = []; basins = []
    cooker_s = None; sink_s = None; s_ = 0.0; mods = []
    for kind in order:
        w = wid[kind]; s0, s1 = s_ + 0.003, s_ + w - 0.003; sc = (s0 + s1) / 2; mods.append((kind, s_, s_ + w))
        if kind == "cooker":
            cooker_s = sc
            stl.append(box(s0, s1, 0.56, 0.6, 0.1, 0.84))                                  # steel oven front
            glassp.append(box(s0 + 0.08, s1 - 0.08, 0.6, 0.605, 0.18, 0.62))                # oven window
            bars.append(bar(s0 + 0.06, s1 - 0.06, 0.64, 0.7))                               # oven handle
            for k in range(4):
                knobs.append(knob(s0 + 0.08 + k * (s1 - s0 - 0.16) / 3, 0.6, 0.79))
            hobs.append(box(s0 + 0.02, s1 - 0.02, 0.06, 0.54, 0.9, 0.906))                  # glass-ceramic hob plate on the worktop
            for rr, (ds, dd) in zip((0.09, 0.07, 0.07, 0.09), ((0.15, 0.17), (0.45, 0.17), (0.15, 0.4), (0.45, 0.4))):
                p0 = W(s0 + (s1 - s0) * ds / 0.6 * 0.6 + 0.0, dd, zf + 0.906); p1 = W(s0 + (s1 - s0) * ds / 0.6 * 0.6 + 0.0, dd, zf + 0.914); rings.append(("cyl", p0, p1, rr, 20))
        else:
            doors.append(box(s0, s1, 0.56, 0.6, 0.1, 0.84)); panels.append(box(s0 + 0.05, s1 - 0.05, 0.6, 0.606, 0.15, 0.79))
            if kind == "sink":
                sink_s = sc; basins.append(box(sc - 0.35, sc + 0.35, 0.08, 0.5, 0.895, 0.9))
                bars.append(bar(sc - 0.25, sc - 0.1, 0.63, 0.78)); bars.append(bar(sc + 0.1, sc + 0.25, 0.63, 0.78))
            else:
                bars.append(bar(sc - 0.08, sc + 0.08, 0.63, 0.78))
        s_ += w
    worktop = [box(-0.01, L + 0.01, 0, 0.64, 0.86, 0.9)]
    back = [box(0, L, 0, 0.015, 0.9, 1.4)]
    # uppers: 0.35 deep at 1.4-2.1, skipped over the cooker (hood) and above the tap
    up = []; upp = []; ubar = []; hs0, hs1 = (cooker_s - 0.45, cooker_s + 0.45) if cooker_s is not None else (1e9, 1e9)
    k_ = 0; cur = 0.0
    while cur < L - 0.1:
        w = min(0.6, L - cur)
        if w < 0.25:
            break
        s0, s1 = cur + 0.003, cur + w - 0.003
        if not (s1 > hs0 and s0 < hs1):
            up.append(box(s0, s1, 0.0, 0.35, 1.4, 2.1)); upp.append(box(s0 + 0.04, s1 - 0.04, 0.35, 0.356, 1.45, 2.05)); ubar.append(bar((s0 + s1) / 2 - 0.07, (s0 + s1) / 2 + 0.07, 0.38, 1.46))
        cur += w; k_ += 1
    groups = [(car, body), (kick, toe), (fm, doors + up), (pm, panels + upp), (tm, worktop), (spl, back), (steel, stl + bars + ubar), (glass, glassp), (knobs and steel or steel, knobs), (hob, hobs), (ring, rings), (basin, basins)]
    fl.mesh_object(f"apt_KitchenRun({r})", groups, bevel=True)
    if sink_s is not None:
        tx, ty, _ = W(sink_s, 0.1, zf + 0.9)
        fx = ra.hssd(r"mixer|basin mixer|faucet|tap", 63 + n, tx, ty, zf + 0.9, {"S": math.pi / 2, "N": -math.pi / 2, "W": 0.0, "E": math.pi}[side], fit=(0.2, 0.28, 0.34), size=(0.1, 0.5))
        if fx is not None:
            _recolour(fx, (0.76, 0.77, 0.79), "ir_apt_ktap_steel", 0.25)
    if cooker_s is not None:
        hx, hy, _ = W(cooker_s, 0.25, zf + 1.55)
        hd_ = ra.hssd(r"chimney hood|cooker hood|range hood", 71 + n, hx, hy, zf + 1.55, {"S": math.pi / 2, "N": -math.pi / 2, "W": 0.0, "E": math.pi}[side], fit=(0.9, 0.5, 0.7), size=(0.5, 1.4), grow=False)
        if hd_ is None:                                                      # built stainless hood + chimney
            hoodm = [box(cooker_s - 0.45, cooker_s + 0.45, 0.0, 0.5, 1.55, 1.7), box(cooker_s - 0.15, cooker_s + 0.15, 0.0, 0.25, 1.7, 2.55)]
            fl.mesh_object(f"apt_Hood({r})", [(steel, hoodm)], bevel=True)
    return len(mods)


def _kitchen(st, stats):
    """P7 r4: realize placed only a bare CafeCounter run + a drinks cooler in the kitchens (REF kitchen: base cabinets, sink, cooker, hood). The counter is replaced by a run of real HSSD base cabinets with a sink cabinet and a cooker, plus a chimney hood on the wall."""
    import wall_face
    ra = _ra(); n = 0
    for r, (lo, hi, t) in _rooms().items():
        u = st[_unit(STY, (lo[0] + hi[0]) / 2)]
        if t != "kitchen" or not u.get("kitchen"):
            continue
        front, top = u["kitchen"]
        for o_ in [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith("DisplayCoolerFactory")]:           # P7 r7: a shop drinks cooler beside a home cooker is out of place (the reference has none)
            c_ = [(o_.matrix_world @ Vector(v_)) for v_ in o_.bound_box]
            if lo[0] - 0.2 < sum(q.x for q in c_) / 8 < hi[0] + 0.2 and lo[1] - 0.2 < sum(q.y for q in c_) / 8 < hi[1] + 0.2:
                bpy.data.objects.remove(o_, do_unlink=True); stats["apt_kitchen_coolers_removed"] = stats.get("apt_kitchen_coolers_removed", 0) + 1
        cs = [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith("CafeCounterFactory") and lo[0] < (_bb(o)[0][0] + _bb(o)[1][0]) / 2 < hi[0] and lo[1] < (_bb(o)[0][1] + _bb(o)[1][1]) / 2 < hi[1]]
        if not cs:
            continue
        a, b = _bb(cs[0]); cx, cy = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2; alongx = (b[0] - a[0]) >= (b[1] - a[1])
        dist = {"S": a[1] - lo[1], "N": hi[1] - b[1], "W": a[0] - lo[0], "E": hi[0] - b[0]}
        side = min(("S", "N"), key=dist.get) if alongx else min(("W", "E"), key=dist.get)
        ins = wall_face.inset(r, side, 0.11); D = 0.62
        yaw = {"S": math.pi / 2, "N": -math.pi / 2, "W": 0.0, "E": math.pi}[side]
        a0, a1 = (a[0], b[0]) if alongx else (a[1], b[1]); a0 = max(a0, (lo[0] if alongx else lo[1]) + 0.3); a1 = min(a1, (hi[0] if alongx else hi[1]) - 0.3); Ltot = a1 - a0
        if Ltot < 1.8:
            continue
        if STY.get("continuous_kitchen"):                                 # P7 r6: one continuous run (butted modules, one worktop, a cooker with hob, sink, uppers, backsplash)
            bpy.data.objects.remove(cs[0], do_unlink=True)
            placed = _kitchen_run(st, u, r, lo, hi, side, alongx, a0, a1, ins, n)
            n += 1; stats.setdefault("apt_kitchen_modules", {})[r] = placed
            continue
        mods = []; rem = Ltot
        if Ltot >= 2.4:
            mods.append(("cooker", 0.9)); rem -= 0.9
        mods.append(("sink", 1.0)); rem -= 1.0
        nb = max(1, int(rem // 0.6)); bw = rem / nb
        order = ["base"] * (nb // 2) + ["sink"] + (["base"] * (nb - nb // 2)) + (["cooker"] if "cooker" in [m[0] for m in mods] else [])
        widths = {"sink": 1.0, "cooker": 0.9, "base": bw}
        u_ = a0; seed = 61 + n * 7; placed = 0; cook_at = None
        bpy.data.objects.remove(cs[0], do_unlink=True)
        for k, kind in enumerate(order):
            w = widths[kind]; c_ = u_ + w / 2
            if side == "S": x, y = c_, lo[1] + ins + D / 2
            elif side == "N": x, y = c_, hi[1] - ins - D / 2
            elif side == "W": x, y = lo[0] + ins + D / 2, c_
            else: x, y = hi[0] - ins - D / 2, c_
            rx, sz = ((r"kitchen cabinet with sink|sink unit|sink cabinet|undermount", (0.6, 2.2)) if kind == "sink" else (r"cooker|cooktop|range|oven", (0.6, 1.4)) if kind == "cooker" else (r"kitchen base cabinet|base cabinet|kitchen cabinet with (door|drawers)", (0.4, 1.2)))
            o = ra.hssd(rx, seed + k, x, y, lo[2], yaw, fit=(w - 0.01, D, 0.92 if kind != "cooker" else 0.95), size=sz, grow=True)
            if o is None:
                continue
            wd = o.dimensions[0]                                                 # the fitted module's real width along the wall (the fit scales uniformly, so it is not always w): pack by real widths, no gaps
            sh = (u_ + wd / 2) - c_
            if alongx:
                o.location.x += sh
            else:
                o.location.y += sh
            cpos = u_ + wd / 2; u_ += wd + 0.005
            if kind != "cooker":
                _recolour(o, front, f"ir_apt_kfront_{int(front[0] * 100)}_{int(front[1] * 100)}", 0.45)
            o.name = f"apt_Kitchen{kind.title()}({r}|{k})"; placed += 1
            if kind == "cooker":
                cook_at = (cpos, x if not alongx else y)
        if cook_at is not None:
            ca = cook_at[0]
            hx, hy = (ca, lo[1] + ins + 0.25) if side == "S" else (ca, hi[1] - ins - 0.25) if side == "N" else (lo[0] + ins + 0.25, ca) if side == "W" else (hi[0] - ins - 0.25, ca)
            ra.hssd(r"chimney hood|cooker hood|range hood", 71 + n, hx, hy, lo[2] + 1.55, yaw, fit=(0.9, 0.5, 0.7), size=(0.5, 1.4), grow=False)
        n += 1; stats.setdefault("apt_kitchen_modules", {})[r] = placed
    stats["apt_kitchen"] = n


def _checker_mat(name="ir_apt_rug_checker"):
    m = bpy.data.materials.get(name)
    if m is not None:
        return m
    m = _flat(name, (0.5, 0.35, 0.22), 0.95); nt = m.node_tree; N, L = nt.nodes, nt.links; b = N["Principled BSDF"]
    tc = N.new("ShaderNodeTexCoord"); ck = N.new("ShaderNodeTexChecker"); ck.inputs["Scale"].default_value = 9.0
    ck.inputs["Color1"].default_value = (0.36, 0.2, 0.12, 1); ck.inputs["Color2"].default_value = (0.9, 0.84, 0.7, 1)
    L.new(tc.outputs["Object"], ck.inputs["Vector"]); L.new(ck.outputs["Color"], b.inputs["Base Color"])
    return m


def _palette(st, stats):
    """P7 r2: the unit colour programmes were missing (cream everywhere). Recolour the layout's sofas / armchairs per unit (A terracotta corduroy, B black-white stripe + red, C dark grey, the pink sitting room floral-pastel) and lay a coloured rug under each living room's coffee table (A checker, B stripe, C grey / jute)."""
    ra = _ra(); n = rg = 0
    for r, (lo, hi, t) in _rooms().items():
        if t != "living-room":
            continue
        u = st[_unit(STY, (lo[0] + hi[0]) / 2)]
        if "sofa" not in u:
            continue
        pink = bool(u.get("pink")) and lo[1] > 6.5
        sofa = u["pink_sofa"] if pink else u["sofa"]; arm = u["pink_arm"] if pink else u["arm"]
        bpy.context.view_layer.update(); cc = None
        for o in bpy.data.objects:
            if o.type != "MESH":
                continue
            a, b = _bb(o)
            if not (lo[0] < (a[0] + b[0]) / 2 < hi[0] and lo[1] < (a[1] + b[1]) / 2 < hi[1]):
                continue
            if o.name.startswith(("AboSofaFactory", "LoveseatFactory")):
                if sofa == "stripe":
                    _set_big_slot(o, _stripe_mat("ir_apt_sofa_stripe", scale=14.0))
                elif pink and STY.get("r2_floral_pink"):
                    _set_big_slot(o, _floral_mat())
                else:
                    _recolour(o, sofa, f"ir_apt_sofa_{int(sofa[0] * 100)}_{int(sofa[1] * 100)}", 0.9)
                n += 1
            elif o.name.startswith(("AboArmchairFactory", "AccentArmchairFactory")):
                _recolour(o, arm, f"ir_apt_arm_{int(arm[0] * 100)}_{int(arm[1] * 100)}", 0.85); n += 1
            elif o.name.startswith("AboCoffeeFactory"):
                cc = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        if cc is None:
            cc = ((lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2)
        for q in [q for q in bpy.data.objects if q.type == "MESH" and q.name.startswith("AboRugFactory") and lo[0] < (_bb(q)[0][0] + _bb(q)[1][0]) / 2 < hi[0] and lo[1] < (_bb(q)[0][1] + _bb(q)[1][1]) / 2 < hi[1]]:
            bpy.data.objects.remove(q, do_unlink=True)                         # the layout's own (red / random) rug makes way for the unit's rug
        rs = u["rug"] if not pink else (0.78, 0.66, 0.45)
        mat = _checker_mat() if rs == "checker" else _stripe_mat("ir_apt_rug_stripe", scale=7.0) if rs == "stripe" else _flat(f"ir_apt_rug_{int(rs[0] * 100)}", rs, 0.95)
        sx, sy = min(2.6, hi[0] - lo[0] - 0.5), min(1.9, hi[1] - lo[1] - 0.5)
        ra.soft(f"apt_LivingRug({r})", mat, cc[0], cc[1], lo[2] + 0.004, sx, sy, 0.02, yaw=0.0, seed=21 + rg, puff=0.05); rg += 1
    stats["apt_palette"] = {"upholstery": n, "rugs": rg}


def _set_big_slot(o, mat):
    """The largest-area slot of an imported piece takes `mat` (a pattern for a sofa body)."""
    if o is None or o.type != "MESH" or not o.data.materials:
        return
    area = {}
    for p in o.data.polygons:
        area[p.material_index] = area.get(p.material_index, 0.0) + p.area
    i = max(area, key=area.get)
    if i < len(o.data.materials):
        o.data = o.data.copy(); o.data.materials[i] = mat


def _decor(st, stats):
    ra = _ra(); n = 0
    for r, (lo, hi, t) in _rooms().items():
        u = st[_unit(STY, (lo[0] + hi[0]) / 2)]
        if t != "living-room" or not u.get("tree"):
            continue
        bpy.context.view_layer.update(); obs = _obstacles(lo, hi)
        spot = _free_patch(lo, hi, obs, 1.1, 1.1, margin=0.3)
        if spot is None:
            continue
        spot = (spot[0], spot[1], 0.0)
        o = ra.hssd(r"christmas tree green|christmas tree", 7, spot[0], spot[1], lo[2], spot[2], fit=(1.1, 1.1, 1.9), size=(1.0, 3.0))
        if o is not None:
            for k in range(6):
                _light(f"ir_apt_tree_{r}_{k}", "POINT", (spot[0] + 0.3 * math.cos(k), spot[1] + 0.3 * math.sin(k), lo[2] + 0.5 + 0.28 * k), 6, (1.0, 0.75, 0.45), r=0.03)
            n += 1
    stats["apt_tree"] = n


STY = None


def _doors_close(st, stats):
    """p8 r10: layout-owned leaves stood open in living rooms / bedrooms (living_0-0 wide3 a third leaf): swing each shut about its hinge into the nearest casing (h2_ref._doors)."""
    from mathutils import Matrix
    LEAF = ("LiteDoorFactory", "LouverDoorFactory", "GlassPanelDoorFactory", "PanelDoorFactory")
    cas = [c for c in bpy.data.objects if c.type == "MESH" and c.name.startswith("DoorCasingFactory")]
    rms = [(lo, hi) for n, (lo, hi, k) in _rooms().items() if n.startswith(("living", "bedroom"))]
    closed = 0
    for o in [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith(LEAF)]:
        b0, b1 = _bb(o); cx, cy = (b0[0] + b1[0]) / 2, (b0[1] + b1[1]) / 2
        if not any(lo[0] - 0.4 < cx < hi[0] + 0.4 and lo[1] - 0.4 < cy < hi[1] + 0.4 for lo, hi in rms) or not cas:
            continue
        cb = {c: _bb(c) for c in cas}
        near = min(cas, key=lambda c: ((cb[c][0][0] + cb[c][1][0]) / 2 - cx) ** 2 + ((cb[c][0][1] + cb[c][1][1]) / 2 - cy) ** 2)
        n0, n1 = cb[near]; ncx, ncy = (n0[0] + n1[0]) / 2, (n0[1] + n1[1]) / 2
        if math.hypot(ncx - cx, ncy - cy) > 1.3:
            continue
        if (b1[0] - b0[0]) < (b1[1] - b0[1]):
            hy = b0[1] if abs(b0[1] - ncy) < abs(b1[1] - ncy) else b1[1]; h = Vector((cx, hy, 0)); d = Vector((0, (b1[1] + b0[1]) - 2 * hy, 0)).normalized()
        else:
            hx = b0[0] if abs(b0[0] - ncx) < abs(b1[0] - ncx) else b1[0]; h = Vector((hx, cy, 0)); d = Vector(((b1[0] + b0[0]) - 2 * hx, 0, 0)).normalized()
        t = Vector((1 if ncx > h.x else -1, 0, 0)) if (n1[0] - n0[0]) > (n1[1] - n0[1]) else Vector((0, 1 if ncy > h.y else -1, 0))
        ang = math.atan2(d.x * t.y - d.y * t.x, d.dot(t))
        if abs(ang) < 0.05:
            continue
        o.matrix_world = Matrix.Translation(h) @ Matrix.Rotation(ang, 4, "Z") @ Matrix.Translation(-h) @ o.matrix_world; closed += 1
    bpy.context.view_layer.update()
    stats["apt_doors_closed"] = closed


# ---------------------------------------------------------------- P9 work rooms (APT7) ----------------------------------------------------------------
# ORCH 2026-10-25 (P9 r2): the craft workroom (unit A) and the home office (unit B) are the scene's reason to exist; apt_shell only floored and lit them.
P9_ROLES = (("craft", 0, 8, 6, 11), ("study", 7.4, 11, 13, 14), ("office", 13, 8, 19, 11))     # rooms.json rects of the three work rooms of APT7
P9_CLEAR = ("OfficeDeskFactory", "TaskChairFactory", "StorageRackFactory", "FilingCabinetFactory", "WhiteboardFactory", "BagFactory", "SoffitFactory", "DuctFactory", "CeilingBeamFactory", "PipeFactory")
P9_LOOSE = ("BookStackFactory", "BookFactory", "CupFactory", "NotebookFactory", "OpenLaptopFactory", "PaperStackFactory", "PenCupFactory", "PhoneFactory", "LanyardFactory")


def _p9_role(lo, hi):
    cx, cy = (lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2
    return next((k for k, x0, y0, x1, y1 in P9_ROLES if x0 <= cx <= x1 and y0 <= cy <= y1), None)


def _in(o, lo, hi):
    a, b = _bb(o)
    return lo[0] < (a[0] + b[0]) / 2 < hi[0] and lo[1] < (a[1] + b[1]) / 2 < hi[1]


def _p9_clear(lo, hi, extra=()):
    """The generator's own office furniture (and whatever stood on a removed desk) makes way for the hand-placed set."""
    import re
    foot = []; n = 0
    names = [o.name for o in bpy.data.objects if o.type == "MESH" and not o.name.startswith(("apt_", "ir_", "Real_")) and _in(o, lo, hi)]
    for nm in names:
        o = bpy.data.objects.get(nm); low = nm.lower()
        if o is None:
            continue
        if nm.startswith(P9_CLEAR + tuple(extra)) or re.search(r"desk|officechair|deskchair|^chairfactory|counterstool|abotablelamp|^abodresser", low):
            a, b = _bb(o)
            if "desk" in low and b[2] - a[2] > 0.4:
                foot.append((a[0] - 0.2, b[0] + 0.2, a[1] - 0.2, b[1] + 0.2))
            bpy.data.objects.remove(o, do_unlink=True); n += 1
    for nm in names:
        o = bpy.data.objects.get(nm)
        if o is not None and nm.startswith(P9_LOOSE):
            a, b = _bb(o); cx, cy = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
            if 0.55 < a[2] < 1.4 and any(f[0] < cx < f[1] and f[2] < cy < f[3] for f in foot):
                bpy.data.objects.remove(o, do_unlink=True); n += 1
    bpy.context.view_layer.update(); dg = bpy.context.evaluated_depsgraph_get()
    for nm in names:                                                   # a book stack / cup whose rack or desk is gone hangs in the air: drop it
        o = bpy.data.objects.get(nm)
        if o is not None and nm.startswith(P9_LOOSE):
            a, b = _bb(o)
            h, loc, _n, _i, _ob, _m = bpy.context.scene.ray_cast(dg, Vector(((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, a[2] - 0.003)), Vector((0, 0, -1)))
            if a[2] > 0.1 and (not h or a[2] - 0.003 - loc.z > 0.04):
                bpy.data.objects.remove(o, do_unlink=True); n += 1
    return n


def _abo_id(aid, x, y, z, yaw, fit=None):
    ra = _ra(); import abo_assets
    e = next((e for e in abo_assets.entries() if e["id"] == aid), None)
    try:
        o = abo_assets._import(e, f"Real_abo({aid})")
    except Exception:                                                  # noqa: BLE001
        ra._count(aid, False); return None
    ra._count(aid, True)
    return ra._stand(o, x, y, z, yaw - math.atan2(ra.ABO_FRONT[1], ra.ABO_FRONT[0]), fit)


def _hs(rx, seed, x, y, z, yaw, fit=None, grow=False):
    o = _ra().hssd(rx, seed, x, y, z, yaw, fit=fit, grow=grow)
    if o is not None:
        o["p9rx"] = rx[:40]                                              # which model regex placed it (visibility diagnostics)
    return o


def _hs_up(rx, seed, x, y, z, yaw, fit=None, grow=False):
    """HSSD wall-class models (wall cabinets, sinks) import lying on their backs (height on y, depth on z, front on +z): bake +90 deg about X so they stand with the ABO front (-y), then place."""
    from mathutils import Matrix
    ra = _ra(); o = ra.hssd(rx, seed, 0.0, 0.0, 0.0, 0.0)
    if o is None:
        return None
    o.data = o.data.copy()                                             # imports of one asset id share a mesh: rotate this object's own copy
    o.data.transform(Matrix.Rotation(math.pi / 2, 4, "X")); o.data.update(); bpy.context.view_layer.update()
    ra._stand(o, x, y, z, yaw - math.atan2(ra.ABO_FRONT[1], ra.ABO_FRONT[0]), fit, grow)
    o["p9rx"] = rx[:40]
    return o


def _wall_pt(r, lo, hi, side, along, off):
    """(x, y, yaw into the room) at `along` the wall `side`, `off` m in front of its inner face (wall_face)."""
    import wall_face
    ins = wall_face.inset(r, side, 0.11)
    return {"S": (along, lo[1] + ins + off, math.pi / 2), "N": (along, hi[1] - ins - off, -math.pi / 2), "W": (lo[0] + ins + off, along, 0.0), "E": (hi[0] - ins - off, along, math.pi)}[side]


def _pegboard_mat(axis):
    name = f"ir_apt_pegboard_{axis}"; m = bpy.data.materials.get(name)
    if m is not None:
        return m
    m = _flat(name, (0.55, 0.4, 0.22), 0.7); nt = m.node_tree; N, L = nt.nodes, nt.links; b = N["Principled BSDF"]
    tc = N.new("ShaderNodeTexCoord"); sp = N.new("ShaderNodeSeparateXYZ"); L.new(tc.outputs["Object"], sp.inputs["Vector"])
    def fr(src):                                                           # fract(coord / 25 mm) - 0.5
        d = N.new("ShaderNodeMath"); d.operation = "MULTIPLY"; d.inputs[1].default_value = 40.0; L.new(src, d.inputs[0])
        f = N.new("ShaderNodeMath"); f.operation = "FRACT"; L.new(d.outputs[0], f.inputs[0])
        s = N.new("ShaderNodeMath"); s.operation = "SUBTRACT"; s.inputs[1].default_value = 0.5; L.new(f.outputs[0], s.inputs[0]); return s.outputs[0]
    cu = fr(sp.outputs["X" if axis == "x" else "Y"]); cv = fr(sp.outputs["Z"])
    cm = N.new("ShaderNodeCombineXYZ"); L.new(cu, cm.inputs["X"]); L.new(cv, cm.inputs["Y"])
    ln = N.new("ShaderNodeVectorMath"); ln.operation = "LENGTH"; L.new(cm.outputs[0], ln.inputs[0])
    hole = N.new("ShaderNodeMath"); hole.operation = "LESS_THAN"; hole.inputs[1].default_value = 0.2; L.new(ln.outputs["Value"], hole.inputs[0])
    mx = N.new("ShaderNodeMix"); mx.data_type = "RGBA"; mx.inputs["A"].default_value = (0.55, 0.4, 0.22, 1); mx.inputs["B"].default_value = (0.04, 0.028, 0.016, 1)
    L.new(hole.outputs[0], mx.inputs["Factor"]); L.new(mx.outputs["Result"], b.inputs["Base Color"])
    return m


def _rattan_mat():
    m = _woven_mat("ir_apt_rattan", (0.3, 0.19, 0.08), 0.35, 90.0); b = m.node_tree.nodes["Principled BSDF"]       # the drum is a real fixture shade: it glows warm
    b.inputs["Emission Color"].default_value = (0.95, 0.64, 0.32, 1.0); b.inputs["Emission Strength"].default_value = 0.0
    return m


def _screen_mat():
    m = bpy.data.materials.get("ir_apt_screen_abstract")
    if m is not None:
        return m
    m = _flat("ir_apt_screen_abstract", (0.02, 0.02, 0.03), 0.2); nt = m.node_tree; N, L = nt.nodes, nt.links; b = N["Principled BSDF"]
    tc = N.new("ShaderNodeTexCoord"); wv = N.new("ShaderNodeTexWave"); wv.inputs["Scale"].default_value = 3.0; wv.inputs["Distortion"].default_value = 6.0
    cr = N.new("ShaderNodeValToRGB"); cr.color_ramp.elements[0].color = (0.04, 0.2, 0.32, 1); cr.color_ramp.elements[1].color = (0.55, 0.22, 0.45, 1)
    L.new(tc.outputs["Object"], wv.inputs["Vector"]); L.new(wv.outputs["Fac"], cr.inputs["Fac"]); L.new(cr.outputs["Color"], b.inputs["Emission Color"]); b.inputs["Emission Strength"].default_value = 0.9
    return m


def _dark_slot(o, mat):
    """Screen face of a monitor: the slot whose material has the darkest base colour."""
    if o is None or o.type != "MESH":
        return False
    best = None
    for i, mt in enumerate(o.data.materials):
        c = tuple(mt.diffuse_color[:3]) if mt is not None else (1, 1, 1)
        if mt is not None and mt.use_nodes and "Principled BSDF" in mt.node_tree.nodes:
            c = tuple(mt.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value[:3])
        if best is None or sum(c) < best[0]:
            best = (sum(c), i)
    if best is None:
        return False
    o.data = o.data.copy(); o.data.materials[best[1]] = mat
    return True


def _shelf_levels(o):
    """World z of the board tops of a shelving unit: rays straight down at a 5 x 3 grid of its footprint, upward-facing hits only; a level needs >= 4 of the 15 columns."""
    a, b = _bb(o); dg = bpy.context.evaluated_depsgraph_get(); sc = bpy.context.scene; zs = []
    for i in range(5):
        for j in range(3):
            x, y, z = a[0] + (b[0] - a[0]) * (i + 0.5) / 5, a[1] + (b[1] - a[1]) * (j + 0.5) / 3, b[2] + 0.05
            for _ in range(14):
                h, loc, nrm, _i, ob, _m = sc.ray_cast(dg, Vector((x, y, z)), Vector((0, 0, -1)))
                if not h:
                    break
                if ob is not None and ob.name == o.name and nrm.z > 0.7:
                    zs.append(loc.z)
                z = loc.z - 0.004
    zs.sort(); groups = []
    for z in zs:
        if groups and z - groups[-1][-1] < 0.03:
            groups[-1].append(z)
        else:
            groups.append([z])
    return [sum(g) / len(g) for g in groups if len(g) >= 4]


P9_SHELF_KINDS = (r"Rattan Basket Small|Basket planter|HSSD_452679|Handy sewing basket", r"Faux Succulents In Low|Potted Succulent|Succulent in Tray|Maiden Hair Fern|Greenery Bonsai|Potted Faux Succulent|Artificial Succulent",
                  r"STORAGE JARS|Vintage large storage jar|Hexagon Jar|Herb Pots", r"Rattan Basket Small|Basket planter|HSSD_452679|Handy sewing basket", r"Faux Succulents In Low|Interior Plant|Ceramic Pot Brown With Potted Fern", r"Jara Terracotta Planter with Stand, Small|San Luis Terracotta Vase|Etruscan Terracotta Trough")


BOOK_COLS = ((0.2, 0.04, 0.04), (0.03, 0.07, 0.13), (0.3, 0.22, 0.07), (0.05, 0.11, 0.06), (0.32, 0.27, 0.19), (0.02, 0.02, 0.022), (0.35, 0.12, 0.05), (0.5, 0.48, 0.42))


def _book(rx, seed, x, y, z, yaw, fit):
    o = _hs(rx, seed, x, y, z, yaw, fit=fit)
    if o is not None:
        i = seed % len(BOOK_COLS); _recol_all(o, BOOK_COLS[i], f"ir_apt_book_{i}", 0.6)
    return o


def _fill_shelves(o, room_c, seed, kinds=None, hmax=0.42):
    """Real baskets / plants / jars on every board of a shelving unit, front toward the room."""
    a, b = _bb(o); lv = _shelf_levels(o); n = 0
    if not lv:
        return 0
    alongx = (b[0] - a[0]) >= (b[1] - a[1]); depth = min(b[0] - a[0], b[1] - a[1]); cx, cy = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
    if alongx:
        yaw = math.pi / 2 if room_c[1] > cy else -math.pi / 2
    else:
        yaw = 0.0 if room_c[0] > cx else math.pi
    L0, L1 = (a[0], b[0]) if alongx else (a[1], b[1])
    for k, z in enumerate(lv):
        up = lv[k + 1] if k + 1 < len(lv) else None
        clear = (up - z - 0.03) if up is not None else 0.45
        if clear < 0.16:
            continue
        s = L0 + 0.12; j = 0
        while s + 0.18 < L1 - 0.08:
            w = 0.36 if j % 3 else 0.3; K = kinds or P9_SHELF_KINDS; rx = K[(k * 2 + j + seed) % len(K)]
            px, py = (s + w / 2, cy) if alongx else (cx, s + w / 2)
            if (_book if rx.startswith("Books") else _hs)(rx, seed * 31 + k * 7 + j, px, py, z, yaw, fit=(w * 0.92, depth * 0.8, min(clear * 0.92, hmax))) is not None:
                n += 1
            s += w + 0.05; j += 1
    return n


def _p9_craft(r, lo, hi, st, stats):
    ra = _ra(); import wall_face
    from room_planner import proc_boutique_flagship as fl
    zc = _zc(r, lo); z0 = lo[2]; rc = ((lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2)
    shelves = [o for o in bpy.data.objects if o.type == "MESH" and _in(o, lo, hi) and not o.name.startswith(("apt_", "Real_")) and any(k in o.name.lower() for k in ("bookcase", "bookshelf", "storagerack", "shelf")) and _bb(o)[1][2] - _bb(o)[0][2] > 1.0]
    pine = _woven_mat("ir_apt_pine", (0.42, 0.26, 0.11), 0.3, 50.0)
    if not shelves:                                                  # two pine bookcases side by side along the first free wall = the IVAR run
        bpy.context.view_layer.update(); sp = _wall_span(r, lo, hi, _obstacles(lo, hi), 2.0, depth=0.5)
        if sp is not None:
            x, y, yaw, side, rect = sp
            for k, d in enumerate((-0.5, 0.5)):
                px, py = (x + d, y) if side in "SN" else (x, y + d)
                o = ra.abo("bookcase", 61 + k, px, py, z0, yaw, fit=(0.95, 0.42, 2.0))
                if o is not None:
                    shelves.append(o)
            bpy.context.view_layer.update()
    for o in shelves:
        _set_big_slot(o, pine)
    bpy.context.view_layer.update(); nb = 0
    for k, o in enumerate(shelves):
        nb += _fill_shelves(o, rc, 5 + k)
    for k, o in enumerate(shelves):                                   # r4: baskets and a terracotta pot on top of every unit
        a_, b_ = _bb(o); ax_ = (b_[0] - a_[0]) >= (b_[1] - a_[1]); cx_, cy_ = (a_[0] + b_[0]) / 2, (a_[1] + b_[1]) / 2
        yw_ = (math.pi / 2 if rc[1] > cy_ else -math.pi / 2) if ax_ else (0.0 if rc[0] > cx_ else math.pi)
        for j, (rx_, d_) in enumerate(((r"Rattan Basket Small|Basket planter", -0.25), (r"Jara Terracotta Planter with Stand, Small|San Luis Terracotta Vase", 0.0), (r"Rattan Basket Small|Basket planter", 0.25))):
            q_ = (cx_ + d_ * (b_[0] - a_[0]) / 0.6, cy_) if ax_ else (cx_, cy_ + d_ * (b_[1] - a_[1]) / 0.6)
            if _hs(rx_, 120 + k * 5 + j, q_[0], q_[1], b_[2], yw_, fit=(0.3, 0.26, 0.32)) is not None:
                nb += 1
    stats["apt_p9_shelf_items"] = nb
    bpy.context.view_layer.update(); obs = _obstacles(lo, hi)
    sp = _wall_span(r, lo, hi, obs, 1.9, depth=0.85) or _wall_span(r, lo, hi, obs, 1.6, depth=0.8)
    if sp is None:
        stats["apt_p9_craft_nodesk"] = 1; return
    x, y, yaw, side, rect = sp
    dk = _hs(r"Verena Glass-Top Sawhorse", 3, x, y, z0, yaw, fit=(1.9, 0.75, 0.76), grow=True)
    if dk is None:
        return
    wh = _flat("ir_apt_trestle_white", (0.94, 0.94, 0.92), 0.5)
    for sl in dk.material_slots:                                       # top and trestle legs: all white (the glass top and brass legs of the asset)
        if sl.material is not None and sl.material.diffuse_color[3] > 0.0 and "::003" not in sl.material.name:
            sl.material = wh
    top = ra.top(dk); fwd = Vector((math.cos(yaw), math.sin(yaw), 0)); lat = Vector((-fwd.y, fwd.x, 0))
    P = Vector((x, y, 0))
    ra.soft(f"apt_CorkMat({r})", _woven_mat("ir_apt_cork", (0.4, 0.26, 0.13), 0.35, 300.0), x, y, top + 0.006, *((0.95, 0.5) if side in "SN" else (0.5, 0.95)), 0.012, yaw=0.0, seed=7, puff=0.05)
    for k, (rx, d_lat, d_fwd) in enumerate(((r"Toyota RA224 Sewing", -0.5, -0.05), (r"STORAGE JARS", 0.55, -0.15), (r"Asparagus Fern, Tall", 0.7, -0.05), (r"Desk Lamp", -0.75, -0.2))):
        q = P + lat * d_lat + fwd * d_fwd
        _hs(rx, 40 + k, q.x, q.y, top + 0.012, yaw + (math.pi if k == 0 else 0.0), fit=(0.34, 0.3, 0.5))
    # pegboard on the wall behind the desk (architecture: a bevelled panel), hooks / shelf / hung baskets in front of it
    W = min(2.4, 1.9 + 0.5); t = 0.02; zb0, zb1 = top + 0.3, min(zc - 0.25, top + 1.45); ins = wall_face.inset(r, side, 0.11)
    wx, wy, _y = _wall_pt(r, lo, hi, side, (x if side in "SN" else y), t / 2 + 0.002)
    prim = ("box", wx, wy, (zb0 + zb1) / 2, W if side in "SN" else t, t if side in "SN" else W, zb1 - zb0)
    fl.mesh_object(f"apt_Pegboard({r})", [(_pegboard_mat("x" if side in "SN" else "y"), [prim])], bevel=True)
    along = x if side in "SN" else y
    def mount(rx, seed, a_, z_, fit, off=0.07):
        px, py, yy = _wall_pt(r, lo, hi, side, a_, t + off); return _hs(rx, seed, px, py, z_, yy, fit=fit)
    mount(r"Porto Wall Hooks", 71, along, zb1 - 0.2, (0.8, 0.1, 0.12), 0.05)
    mount(r"Wall Shelf, Nature", 72, along + 0.45, zb0 + 0.55, (0.7, 0.3, 0.3), 0.045)
    for k, (rx, d_, zz) in enumerate(((r"Basket planter", -0.65, zb0 + 0.3), (r"Rattan Basket Small", -0.2, zb0 + 0.38), (r"HSSD_452679", 0.2, zb0 + 0.2))):
        mount(rx, 80 + k, along + d_, zz, (0.3, 0.16, 0.3), 0.08)
    for k, (rx, d_) in enumerate(((r"Faux Succulents In Low", 0.25), (r"Vintage large storage jar", 0.5), (r"Artificial Succulent", 0.65))):
        mount(rx, 90 + k, along + d_, zb0 + 0.58, (0.16, 0.16, 0.22), 0.1)
    # jute rug in front of the desk, stool, rattan drum pendant over the work area
    q = P + fwd * 1.0
    rug = _hs(r"Lacie 6' x 9' Handwoven Rug in Natural", 5, q.x, q.y, z0, 0.0, fit=(2.4, 1.6, 0.05))
    if rug is not None:
        _set_big_slot(rug, _woven_mat("ir_apt_jute", (0.4, 0.3, 0.17), 0.3, 260.0))
    st_ = ra.abo("stool", 91, (P + fwd * 0.75 + lat * 0.1).x, (P + fwd * 0.75 + lat * 0.1).y, z0, yaw + math.pi)
    _recolour(st_, (0.5, 0.5, 0.5), "ir_apt_stool_grey", 0.6)
    c = P + fwd * 0.6
    pd = _hs(r"Pleat Drum Pendant, Light Grey", 12, c.x, c.y, zc - 0.9, 0.0, fit=(0.5, 0.5, 0.7), grow=True)
    if pd is not None:
        _set_big_slot(pd, _rattan_mat())
        _light(f"ir_apt_rattan_{r}", "POINT", (c.x, c.y, zc - 0.62), 45, (1.0, 0.8, 0.55), r=0.2)
    nl = 0                                                            # r5 (REF): bamboo lanterns on the floor at the ends of the pine run, each with a small warm light inside
    for k, sh in enumerate(shelves[:2]):
        a_, b_ = _bb(sh); ax_ = (b_[0] - a_[0]) >= (b_[1] - a_[1]); cx_, cy_ = (a_[0] + b_[0]) / 2, (a_[1] + b_[1]) / 2
        dx_, dy_ = ((b_[0] - a_[0]) / 2 + 0.3, 0.0) if ax_ else (0.0, (b_[1] - a_[1]) / 2 + 0.3)
        qx_, qy_ = cx_ + (dx_ if rc[0] > cx_ else -dx_), cy_ + (dy_ if rc[1] > cy_ else -dy_)
        qx_, qy_ = (qx_, qy_ + (0.1 if rc[1] > cy_ else -0.1)) if ax_ else (qx_ + (0.1 if rc[0] > cx_ else -0.1), qy_)
        if not (lo[0] + 0.2 < qx_ < hi[0] - 0.2 and lo[1] + 0.2 < qy_ < hi[1] - 0.2):
            continue
        ln = _hs(r"BAMBOO LANTERN LARGE", 130 + k, qx_, qy_, z0, 0.0, fit=(0.42, 0.42, 0.95), grow=True)
        if ln is not None:
            _recol_all(ln, (0.52, 0.33, 0.14), "ir_apt_bamboo_lantern", 0.55)
            nl += 1; _light(f"ir_apt_lantern_{r}_{k}", "POINT", (qx_, qy_, z0 + 0.33), 6, (1.0, 0.75, 0.45), r=0.05)
    stats["apt_p9_craft"] = {"desk": 1, "rug": int(rug is not None), "pendant": int(pd is not None), "lanterns": nl}


def _p9_office(r, lo, hi, st, stats):
    ra = _ra(); z0 = lo[2]; zc = _zc(r, lo)
    bpy.context.view_layer.update(); obs = _obstacles(lo, hi)
    sp = _wall_span(r, lo, hi, obs, 2.0, depth=0.85) or _wall_span(r, lo, hi, obs, 1.7, depth=0.8)
    if sp is None:
        stats["apt_p9_office_nodesk"] = 1; return
    x, y, yaw, side, rect = sp
    dk = _hs(r"Brophy Sit-Stand", 3, x, y, z0, yaw, fit=(1.75, 0.8, 0.74), grow=True)
    if dk is None:
        return
    _set_big_slot(dk, _woven_mat("ir_apt_walnut", (0.028, 0.013, 0.007), 0.3, 40.0))
    top = ra.top(dk); fwd = Vector((math.cos(yaw), math.sin(yaw), 0)); lat = Vector((-fwd.y, fwd.x, 0)); P = Vector((x, y, 0)); back = -fwd
    ra.soft(f"apt_DeskPad({r})", _flat("ir_apt_leather_pad", (0.07, 0.05, 0.04), 0.5), x + fwd.x * 0.05, y + fwd.y * 0.05, top + 0.004, *((0.85, 0.4) if side in "SN" else (0.4, 0.85)), 0.008, yaw=0.0, seed=8, puff=0.03)
    b = P + back * 0.3
    sc = _hs(r"Screen, Fabric Magnetic Grey", 4, b.x + back.x * 0.05, b.y + back.y * 0.05, top + 0.01, yaw, fit=(1.2, 0.1, 0.34), grow=True)
    q = P + back * 0.12
    rz = _abo_id("B00X4SCCFG", q.x, q.y, top + 0.005, yaw, fit=(0.6, 0.3, 0.14))
    zt = ra.top(rz) if rz is not None else top
    mo = _hs(r"Apple Cinema Display 30", 5, q.x, q.y, zt, yaw, fit=(0.66, 0.2, 0.52))
    if mo is not None:
        _dark_slot(mo, _screen_mat())
    for k, (rx, d_) in enumerate(((r"Faux Succulents In Low", 0.75), (r"Desk Lamp", -0.75))):
        p_ = P + lat * d_ + back * 0.12
        _hs(rx, 50 + k, p_.x, p_.y, top + 0.005, yaw, fit=(0.2, 0.2, 0.3))
    ch = P + fwd * 0.62
    cr = _abo_id("B06W5XBL3D", ch.x, ch.y, z0, yaw + math.pi, fit=(0.62, 0.62, 1.0))
    _set_big_slot(cr, _flat("ir_apt_chair_black", (0.02, 0.02, 0.022), 0.5))
    cq = P + fwd * 0.45; c = (cq.x, cq.y)                               # r4: over the desk, not over the middle of the room (the probe cameras stand under that one)
    pd = _hs(r"Harmony Ribboned Pendant, Natural, Large", 6, c[0], c[1], zc - 0.55, 0.0, fit=(0.6, 0.6, 0.55), grow=True)
    if pd is not None:
        _set_big_slot(pd, _flat("ir_apt_pendant_black", (0.015, 0.015, 0.017), 0.35))
        _light(f"ir_apt_wavy_{r}", "AREA", (c[0], c[1], zc - 0.62), 38, (1.0, 0.88, 0.7), sx=0.4, sy=0.4)
    try:
        _p9_office_fill(r, lo, hi, side, x, y, yaw, top, P, fwd, lat, stats)
    except Exception as ex:                                           # noqa: BLE001
        import traceback; traceback.print_exc(); stats["apt_p9_office_fill_error"] = repr(ex)[:160]
    stats["apt_p9_office"] = {"desk": 1, "monitor": int(mo is not None), "screen": int(sc is not None), "chair": int(cr is not None), "pendant": int(pd is not None)}


def _p9_office_fill(r, lo, hi, side, x, y, yaw, top, P, fwd, lat, stats):
    """r4 (REF 02): beige loop carpet, white wall shelves with magazine files above the desk, white sideboard, white rolling cart, the layout's bookcase painted white and filled."""
    ra = _ra(); z0 = lo[2]; got = {}
    ra.soft(f"apt_LoopCarpet({r})", _woven_mat("ir_apt_loop_carpet", (0.5, 0.45, 0.37), 0.3, 420.0), P.x + fwd.x * 0.5, P.y + fwd.y * 0.5, z0 + 0.009, *((2.4, 1.7) if side in "SN" else (1.7, 2.4)), 0.018, yaw=0.0, seed=11, puff=0.05)
    white = _flat("ir_apt_shelf_white", (0.94, 0.94, 0.92), 0.5); nsh = 0
    for k, dz in enumerate((0.75, 1.17)):
        px, py, yy = _wall_pt(r, lo, hi, side, x if side in "SN" else y, 0.045)
        sh = _hs(r"Wall Shelf, Culture", 17 + k, px, py, top + dz, yy, fit=(1.3, 0.3, 0.3), grow=True)
        if sh is None:
            continue
        _set_big_slot(sh, white); nsh += 1; ax = Vector((1, 0, 0)) if side in "SN" else Vector((0, 1, 0))
        for j in range(4 if k == 0 else 2):
            q = Vector((px, py, 0)) + ax * (-0.5 + 0.33 * j)
            _book(r"Books for Wall Shelves|Home Design Interiors Magazine", 30 + k * 6 + j, q.x, q.y, top + dz + 0.03, yy, (0.28, 0.2, 0.3))
        if k == 1:
            q = Vector((px, py, 0)) + ax * 0.45
            _hs(r"Faux Succulents In Low", 40, q.x, q.y, top + dz + 0.03, yy, fit=(0.2, 0.2, 0.28))
    got["shelves"] = nsh
    bpy.context.view_layer.update(); obs = _obstacles(lo, hi)
    sp = _strip(r, lo, hi, obs, 1.5, 0.45, prefer="N")
    if sp is not None:
        sx_, sy_, syaw, sside, _rc = sp
        sb = _hs(r"Coby sideboard|Seaside Sideboard|Sideboard", 61, sx_, sy_, z0, syaw, fit=(1.5, 0.42, 0.8)); _recol_all(sb, (0.92, 0.92, 0.9), "ir_apt_sideboard_white", 0.5)
        if sb is not None:
            tp = ra.top(sb); ex = Vector((1, 0, 0)) if sside in "SN" else Vector((0, 1, 0))
            for j, rx in enumerate((r"Faux Succulents In Low", r"Rattan Basket Small|Basket planter")):
                q = Vector((sx_, sy_, 0)) + ex * (-0.45 + 0.9 * j)
                _hs(rx, 62 + j, q.x, q.y, tp, syaw, fit=(0.26, 0.24, 0.3))
        got["sideboard"] = int(sb is not None)
    bpy.context.view_layer.update(); obs = _obstacles(lo, hi)
    sp = _strip(r, lo, hi, obs, 0.6, 0.45, prefer="E")
    if sp is not None:
        cart = _hs(r"Craftsman Bar Cart", 63, sp[0], sp[1], z0, sp[2], fit=(0.6, 0.4, 0.8)); _recol_all(cart, (0.93, 0.93, 0.91), "ir_apt_cart_white", 0.5); got["cart"] = int(cart is not None)
    for o in [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith("AboBookcaseFactory") and _in(o, lo, hi)]:
        _recol_all(o, (0.93, 0.93, 0.91), "ir_apt_bookcase_white", 0.5); got["bookcase_items"] = _fill_shelves(o, ((lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2), 7)
    stats["apt_p9_office_fill"] = got


def _strip(r, lo, hi, obs, L, depth, prefer="N"):
    """_wall_span with a preferred wall order (the first free L x depth strip against `prefer` first, then the others longest first)."""
    import wall_face
    sides = sorted("SNWE", key=lambda s_: (s_ != prefer, -((hi[0] - lo[0]) if s_ in "SN" else (hi[1] - lo[1]))))
    for s_ in sides:
        ins = wall_face.inset(r, s_, 0.11)
        along = (lo[0] + 0.3, hi[0] - 0.3) if s_ in "SN" else (lo[1] + 0.3, hi[1] - 0.3)
        mid = (along[0] + along[1]) / 2; us = []; k = 0.0
        while mid - k >= along[0] + L / 2 or mid + k <= along[1] - L / 2:                  # from the middle of the wall outwards
            for sg in (1, -1) if k else (1,):
                u_ = mid + sg * k
                if along[0] + L / 2 <= u_ <= along[1] - L / 2:
                    us.append(u_)
            k += 0.2
        for u_ in us:
            if s_ == "S":
                x, y, yaw, rc = u_, lo[1] + ins + depth / 2, math.pi / 2, (u_ - L / 2, u_ + L / 2, lo[1], lo[1] + ins + depth)
            elif s_ == "N":
                x, y, yaw, rc = u_, hi[1] - ins - depth / 2, -math.pi / 2, (u_ - L / 2, u_ + L / 2, hi[1] - ins - depth, hi[1])
            elif s_ == "W":
                x, y, yaw, rc = lo[0] + ins + depth / 2, u_, 0.0, (lo[0], lo[0] + ins + depth, u_ - L / 2, u_ + L / 2)
            else:
                x, y, yaw, rc = hi[0] - ins - depth / 2, u_, math.pi, (hi[0] - ins - depth, hi[0], u_ - L / 2, u_ + L / 2)
            if not any(rc[0] < q[1] and q[0] < rc[1] and rc[2] < q[3] and q[2] < rc[3] for q in obs):
                return x, y, yaw, s_, rc
    return None


def _picture(rx, seed, x, y, zb, yaw, wmax, hmax):
    """A framed print stood upright (HSSD pictures are modelled flat: width x, height y, thickness z), front toward heading `yaw`, bottom edge on zb."""
    from mathutils import Matrix
    o = _hs(rx, seed, 0.0, 0.0, 0.0, 0.0)
    if o is None:
        return None
    w, h = o.dimensions[0], o.dimensions[1]; k = min(wmax / max(w, 1e-4), hmax / max(h, 1e-4), 1.6)
    rz = yaw + math.pi / 2
    R = Matrix.Rotation(rz, 3, "Z") @ Matrix.Rotation(math.pi / 2, 3, "X") @ Matrix.Diagonal((k, k, k))
    q = [R @ Vector(c) for c in o.bound_box]
    cx, cy, zmin = (min(p.x for p in q) + max(p.x for p in q)) / 2, (min(p.y for p in q) + max(p.y for p in q)) / 2, min(p.z for p in q)
    o.rotation_mode = "XYZ"; o.rotation_euler = (math.pi / 2, 0, rz); o.scale = (k, k, k); o.location = (x - cx, y - cy, zb - zmin + 0.002)
    return o


def _recol_all(o, rgb, name, rough=0.5):
    """Every slot that carries > 8 % of the surface (not glass) takes the flat colour: a trolley / cabinet whose frame, shelves and top are separate slots."""
    if o is None or o.type != "MESH":
        return o
    area = {}
    for p_ in o.data.polygons:
        area[p_.material_index] = area.get(p_.material_index, 0.0) + p_.area
    tot = sum(area.values()) or 1.0; o.data = o.data.copy(); m = _flat(name, rgb, rough)
    for i_, a_ in area.items():
        if a_ / tot > 0.08 and i_ < len(o.data.materials) and "glass" not in (o.data.materials[i_].name.lower() if o.data.materials[i_] else ""):
            o.data.materials[i_] = m
    return o


def _recol(o, rgb, name, rough=0.5):
    if o is not None:
        _recolour(o, rgb, name, rough)
    return o


def _p9_doorway_curtain(r, lo, hi, mat=None, tag="Door", only_one=False, skip_leaf=False):
    """REF 06: a cream curtain hangs in the doorway, tied back to both sides (the opening stays walkable). The generator's open door leaf goes."""
    from room_planner import proc_boutique_flagship as fl
    cas = [c for c in bpy.data.objects if c.type == "MESH" and c.name.startswith("DoorCasingFactory") and _in(c, (lo[0] - 0.5, lo[1] - 0.5, 0), (hi[0] + 0.5, hi[1] + 0.5, 9))]
    n = 0; lin = mat or _woven_mat("ir_apt_curtain_cream", (0.88, 0.83, 0.7), 0.08, 120.0); brass = _flat("ir_apt_rod_brass", (0.72, 0.52, 0.22), 0.3, 1.0)
    for c in cas:
        if only_one and n:
            break
        b0, b1 = _bb(c)
        if b1[2] - b0[2] < 1.8:
            continue
        along_x = (b1[0] - b0[0]) > (b1[1] - b0[1])
        cx, cy = (b0[0] + b1[0]) / 2, (b0[1] + b1[1]) / 2
        a0, a1 = (b0[0], b1[0]) if along_x else (b0[1], b1[1])
        if a1 - a0 < 0.7 or a1 - a0 > 2.2:
            continue
        mid = ((lo[1] + hi[1]) / 2) if along_x else ((lo[0] + hi[0]) / 2); wallc = cy if along_x else cx
        if abs(wallc - (lo[1] if along_x else lo[0])) > 0.5 and abs(wallc - (hi[1] if along_x else hi[0])) > 0.5:
            continue
        side = 1 if wallc < mid else -1; line = wallc + side * 0.2; zt = lo[2] + 2.2
        for o in [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith(("PanelDoorFactory", "GlassPanelDoorFactory", "LiteDoor", "LouverDoor")) and _in(o, (lo[0] - 0.2, lo[1] - 0.2, 0), (hi[0] + 0.2, hi[1] + 0.2, 9))
                  and abs(((_bb(o)[0][1] + _bb(o)[1][1]) / 2 if along_x else (_bb(o)[0][0] + _bb(o)[1][0]) / 2) - wallc) < 1.0]:
            bpy.data.objects.remove(o, do_unlink=True)
        _pleat_panel(f"apt_{tag}CurtainL({r}|{n})", lin, a0 + 0.05, a0 + 0.5, lo[2] + 0.02, zt, line, side, along_x, 4, 0.07, 3 + n)
        _pleat_panel(f"apt_{tag}CurtainR({r}|{n})", lin, a1 - 0.5, a1 - 0.05, lo[2] + 0.02, zt, line, side, along_x, 4, 0.07, 9 + n)
        p0 = (a0, line, zt + 0.03, a1, line, zt + 0.03) if along_x else (line, a0, zt + 0.03, line, a1, zt + 0.03)
        fl.mesh_object(f"apt_DoorRod({r}|{n})", [(brass, [("cyl", (p0[0], p0[1], p0[2]), (p0[3], p0[4], p0[5]), 0.012, 8)])], bevel=False)
        n += 1
    return n


def _p9_study(r, lo, hi, st, stats):
    """Unit A study (REF photo 06): white drop-leaf desk under the window, white study chair, desk lamp, white wall shelves with books, sage trolley, dark glass-door cabinet."""
    ra = _ra(); z0 = lo[2]
    bpy.context.view_layer.update(); obs = _obstacles(lo, hi)
    sp = _strip(r, lo, hi, obs, 1.5, 0.75, prefer="N")
    got = {}
    if sp is not None:
        x, y, yaw, side, rect = sp
        dk = _hs(r"Kendall Desk, White", 3, x, y, z0, yaw, fit=(1.5, 0.7, 0.76), grow=True); got["desk"] = int(dk is not None)
        if dk is not None:
            top = ra.top(dk); fwd = Vector((math.cos(yaw), math.sin(yaw), 0)); lat = Vector((-fwd.y, fwd.x, 0)); P = Vector((x, y, 0))
            q = P + fwd * 0.62
            got["chair"] = int(_hs(r"Channel Back Armless Office Chair, White", 4, q.x, q.y, z0, yaw + math.pi, fit=(0.6, 0.6, 0.9)) is not None)
            q = P + lat * -0.5 - fwd * 0.12
            lp = _hs(r"Desk Lamp", 5, q.x, q.y, top + 0.005, yaw, fit=(0.24, 0.24, 0.4))
            if lp is not None:
                _light(f"ir_apt_studylamp_{r}", "POINT", (q.x, q.y, top + 0.3), 20, (1.0, 0.8, 0.55), r=0.06)
            q = P + lat * 0.35 - fwd * 0.12
            _hs(r"Faux Succulents In Low", 6, q.x, q.y, top + 0.005, yaw, fit=(0.18, 0.18, 0.25))
            for k, dz in enumerate((0.62, 1.0)):                              # white floating shelves with books above the desk
                px, py, yy = _wall_pt(r, lo, hi, side, x if side in "SN" else y, 0.045)
                sh = _hs(r"Wall Shelf, Culture", 7 + k, px, py, top + dz, yy, fit=(1.1, 0.3, 0.3), grow=True)
                if sh is not None:
                    _set_big_slot(sh, _flat("ir_apt_shelf_white", (0.94, 0.94, 0.92), 0.5))
                    for j in range(3):
                        q = Vector((px, py, 0)) + (Vector((1, 0, 0)) if side in "SN" else Vector((0, 1, 0))) * (-0.36 + 0.36 * j)
                        _book(r"Books for Wall Shelves", 20 + k * 5 + j, q.x, q.y, top + dz + 0.03, yy, (0.3, 0.16, 0.26))
            got["shelves"] = 2
            cw_ = lo[1] + (hi[1] - lo[1]) * 0.9                              # r5: on the west wall beside the curtained doorway (the wide7 view looks that way), flat HSSD clocks stand up via _picture
            px, py, yy = _wall_pt(r, lo, hi, "W", cw_, 0.03)
            ck = _picture(r"Emmet Wall Clock", 12, px, py, z0 + 1.55, yy, 0.42, 0.42); got["clock"] = int(ck is not None)
    bpy.context.view_layer.update(); obs = _obstacles(lo, hi)
    sp2 = _strip(r, lo, hi, obs, 0.85, 0.55, prefer="E") or _strip(r, lo, hi, obs, 0.85, 0.55, prefer="S")
    if sp2 is not None:
        x, y, yaw, side, rect = sp2
        gc = _hs(r"Built-in Glass Door Cabinet", 8, x, y, z0, yaw, fit=(0.9, 0.5, 2.0))
        _recol_all(gc, (0.025, 0.015, 0.01), "ir_apt_cabinet_dark", 0.4); got["cabinet"] = int(gc is not None)
    bpy.context.view_layer.update(); obs = _obstacles(lo, hi)
    sp3 = _strip(r, lo, hi, obs, 0.7, 0.5, prefer="S")
    if sp3 is not None:
        x, y, yaw, side, rect = sp3
        tr = _hs(r"Craftsman Bar Cart", 9, x, y, z0, yaw, fit=(0.8, 0.45, 0.8))
        _recol_all(tr, (0.55, 0.63, 0.52), "ir_apt_trolley_sage", 0.55); got["trolley"] = int(tr is not None)
    try:
        got["curtain"] = _p9_doorway_curtain(r, lo, hi)
    except Exception as ex:                                           # noqa: BLE001
        import traceback; traceback.print_exc(); got["curtain_error"] = repr(ex)[:120]
    stats["apt_p9_study"] = got


def _p9_nook_cabinets(r, lo, hi, tb, tx, ty, z0):
    """r4 (REF 03): the counter run goes dark-brown with a walnut worktop, glazed wall cabinets above it, a small potted fir on the table."""
    ra = _ra(); got = {}
    dark = _woven_mat("ir_apt_cab_dark", (0.045, 0.022, 0.013), 0.15, 60.0); wal = _woven_mat("ir_apt_worktop_walnut", (0.035, 0.017, 0.009), 0.3, 40.0)
    for o in [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith("CafeCounterFactory") and _in(o, lo, hi)]:
        o.data = o.data.copy()
        for i, m in enumerate(o.data.materials):
            if m is not None and m.name.startswith("ir_counter_forest_flut"):
                o.data.materials[i] = dark
            elif m is not None and m.name.startswith("ir_counter_top"):
                o.data.materials[i] = wal
        a, b = _bb(o); got["counter"] = 1
        ax = (b[0] - a[0]) >= (b[1] - a[1]); side = ("N" if abs(b[1] - hi[1]) < abs(a[1] - lo[1]) else "S") if ax else ("E" if abs(b[0] - hi[0]) < abs(a[0] - lo[0]) else "W")
        u0, u1 = (a[0], b[0]) if ax else (a[1], b[1]); n = 0
        u = u0 + 0.45
        while u + 0.4 < u1 - 0.9 and n < 4:                           # leave the fridge end clear
            px, py, yy = _wall_pt(r, lo, hi, side, u + 0.4, 0.2)
            cb = _hs_up(r"Kitchen wall cabinet with 2 glass doors", 70 + n, px, py, z0 + 1.5, yy, fit=(0.8, 0.38, 0.75))
            if cb is not None:
                _recol_all(cb, (0.045, 0.022, 0.013), "ir_apt_cab_upper_dark", 0.4); n += 1
                for i_, m_ in enumerate(cb.data.materials):                # the door glass: fluted, frosted
                    if m_ is not None and m_.name.startswith("HSSD_MAT"):
                        cb.data.materials[i_] = _fluted_glass_mat()
            u += 0.82
        got["uppers"] = n
        try:                                                           # r5: a black vessel sink with a tap on the walnut worktop, under the middle of the wall-cabinet run
            um = u0 + 0.45 + 0.41 * max(n, 1)
            sx_, sy_, syy = _wall_pt(r, lo, hi, side, um, 0.33)
            sk = _hs(r"Round Sink Double, Flat", 3, sx_, sy_, b[2], syy + math.pi / 2, fit=(0.7, 0.45, 0.4))
            if sk is not None:
                _recol_all(sk, (0.02, 0.02, 0.022), "ir_apt_sink_black", 0.3); got["sink"] = 1
        except Exception as ex:                                       # noqa: BLE001
            import traceback; traceback.print_exc(); got["sink_error"] = repr(ex)[:120]
    tp = ra.top(tb) if tb is not None else None
    if tp is not None:
        fr = _hs(r"Christmas Tree Green", 7, tx + 0.15, ty, tp, 0.0, fit=(0.42, 0.42, 0.62)); got["fir"] = int(fr is not None)
    return got


def _p9_nook(r, lo, hi, st, stats):
    """Unit B kitchen_0/1 = the craft / dining nook (REF photo 03): the long dark table + yellow chairs become a round walnut table with four white swivel chairs, a white petal pendant,
    a pair of picture ledges with leaning frames; the mauve walls, dark-brown cabinets and the small tree stay."""
    ra = _ra(); z0 = lo[2]; zc = _zc(r, lo); got = {}
    for o in [o for o in bpy.data.objects if o.type == "MESH" and _in(o, lo, hi) and (o.name.startswith(("TableDiningFactory", "ChairFactory", "Real_deskchair")) or (o.name.startswith("Real_hssd(") and _bb(o)[0][2] > 1.5))]:
        bpy.data.objects.remove(o, do_unlink=True)
    for o in [o for o in bpy.data.objects if o.type == "LIGHT" and o.name.startswith(f"ir_apt_pleat_{r}")]:
        bpy.data.objects.remove(o, do_unlink=True)
    bpy.context.view_layer.update(); obs = _obstacles(lo, hi)
    spot = _free_patch(lo, hi, obs, 2.0, 2.0, margin=0.3) or _free_patch(lo, hi, obs, 1.7, 1.7, margin=0.3)
    if spot is None:
        stats["apt_p9_nook_nospot"] = 1; return
    x, y = spot
    tb = _hs(r"SPENCER ROUND DINING TABLE", 5, x, y, z0, 0.0, fit=(1.2, 1.2, 0.76), grow=True)
    _set_big_slot(tb, _woven_mat("ir_apt_walnut_table", (0.03, 0.014, 0.008), 0.3, 40.0)); got["table"] = int(tb is not None)
    nch = 0
    for k in range(4):
        a = math.pi / 2 * k + 0.4; cx, cy = x + 0.82 * math.cos(a), y + 0.82 * math.sin(a)
        ch = _hs(r"Textured Barrel Swivel Chair, White", 31 + k, cx, cy, z0, a + math.pi, fit=(0.7, 0.7, 0.85))
        if ch is not None:
            nch += 1
    got["chairs"] = nch
    pd = _hs(r"PH Artichoke Lamp - Medium, White", 6, x, y, zc - 1.05, 0.0, fit=(0.62, 0.62, 1.05), grow=True)
    if pd is not None:
        _light(f"ir_apt_petal_{r}", "POINT", (x, y, zc - 0.85), 50, (1.0, 0.8, 0.58), r=0.2)
    got["pendant"] = int(pd is not None)
    bpy.context.view_layer.update(); obs = _obstacles(lo, hi)
    sp = _strip(r, lo, hi, obs, 1.4, 0.3, prefer="W")
    nf = 0
    if sp is not None:
        px, py, yaw, side, rect = sp; along = px if side in "SN" else py
        ax = Vector((1, 0, 0)) if side in "SN" else Vector((0, 1, 0))
        for k, zz in enumerate((1.3, 1.7)):
            qx, qy, yy = _wall_pt(r, lo, hi, side, along, 0.045)
            sh = _hs(r"Wall Shelf, Culture", 40 + k, qx, qy, z0 + zz, yy, fit=(0.95, 0.3, 0.3), grow=True)
            if sh is None:
                continue
            _set_big_slot(sh, _flat("ir_apt_ledge_white", (0.94, 0.94, 0.92), 0.5))
            for j in range(3):
                q = Vector((qx, qy, 0)) + ax * (-0.3 + 0.3 * j) + Vector((math.cos(yy), math.sin(yy), 0)) * 0.03
                if _picture(r"Balian Beach Art|Infinity Aperture Photo Frame|New York Picture and Frame|PICTURE, BICYCLE|Red Sails|White sun umbrellas", 50 + k * 4 + j, q.x, q.y, ra.top(sh), yy, 0.38, 0.42) is not None:
                    nf += 1
    got["frames"] = nf
    try:
        got.update(_p9_nook_cabinets(r, lo, hi, tb, x, y, z0))
    except Exception as ex:                                           # noqa: BLE001
        import traceback; traceback.print_exc(); got["cab_error"] = repr(ex)[:120]
    stats["apt_p9_nook"] = got


def _floral_mat():
    m = bpy.data.materials.get("ir_apt_floral")
    if m is not None:
        return m
    m = _flat("ir_apt_floral", (0.93, 0.9, 0.82), 0.85); nt = m.node_tree; N, L = nt.nodes, nt.links; b = N["Principled BSDF"]
    tc = N.new("ShaderNodeTexCoord"); vo = N.new("ShaderNodeTexVoronoi"); vo.inputs["Scale"].default_value = 7.0
    rp = N.new("ShaderNodeValToRGB"); e = rp.color_ramp.elements; e[0].position = 0.0; e[0].color = (0.62, 0.15, 0.2, 1); e[1].position = 0.3; e[1].color = (0.93, 0.9, 0.82, 1)
    e2 = rp.color_ramp.elements.new(0.16); e2.color = (0.78, 0.35, 0.38, 1)
    L.new(tc.outputs["Object"], vo.inputs["Vector"]); L.new(vo.outputs["Distance"], rp.inputs["Fac"]); L.new(rp.outputs["Color"], b.inputs["Base Color"])
    return m


def _fluted_glass_mat():
    m = bpy.data.materials.get("ir_apt_fluted_glass")
    if m is not None:
        return m
    m = _flat("ir_apt_fluted_glass", (0.62, 0.55, 0.45), 0.3); nt = m.node_tree; N, L = nt.nodes, nt.links; b = N["Principled BSDF"]
    if "Transmission Weight" in b.inputs:
        b.inputs["Transmission Weight"].default_value = 0.55
    tc = N.new("ShaderNodeTexCoord"); wv = N.new("ShaderNodeTexWave"); wv.wave_type = "BANDS"; wv.bands_direction = "X"; wv.inputs["Scale"].default_value = 70.0; wv.inputs["Distortion"].default_value = 0.0
    bp = N.new("ShaderNodeBump"); bp.inputs["Strength"].default_value = 0.8; bp.inputs["Distance"].default_value = 0.004
    L.new(tc.outputs["Object"], wv.inputs["Vector"]); L.new(wv.outputs["Fac"], bp.inputs["Height"]); L.new(bp.outputs["Normal"], b.inputs["Normal"])
    return m


def _glass_partition(r, x, y, along_x, W, H, z0):
    """Black-framed glass partition panel (architecture: bevelled frame prims + a glass pane)."""
    from room_planner import proc_boutique_flagship as fl
    blk = _flat("ir_apt_frame_black", (0.015, 0.015, 0.017), 0.35, 0.3)
    gl = _flat("ir_apt_shower_glass", (0.85, 0.9, 0.92), 0.03); b2 = gl.node_tree.nodes["Principled BSDF"]
    if "Transmission Weight" in b2.inputs:
        b2.inputs["Transmission Weight"].default_value = 0.92
    d, t = 0.05, 0.04; sx, sy = (W, d) if along_x else (d, W)
    fr = [("box", x, y, z0 + H - t / 2, sx, sy, t), ("box", x, y, z0 + t / 2, sx, sy, t), ("box", x, y, z0 + H * 0.55, sx, sy, t * 0.7)]
    for u in (-W / 2 + t / 2, -W / 6, W / 6, W / 2 - t / 2):
        fr.append(("box", x + u, y, z0 + H / 2, t, d, H) if along_x else ("box", x, y + u, z0 + H / 2, d, t, H))
    pane = [("box", x, y, z0 + H / 2, (W - 2 * t) if along_x else 0.01, 0.01 if along_x else (W - 2 * t), H - 2 * t)]
    fl.mesh_object(f"apt_GlassPartition({r})", [(gl, pane), (blk, fr)], bevel=True)


def _tree_deco(r, a, b):
    """Christmas tree: red and gold baubles and a warm LED string spiralling down the cone (the string beads are the only emitters, a real fixture)."""
    import bmesh, random
    from mathutils import Matrix
    rg = random.Random(5); cx, cy = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2; zb, zt = a[2] + 0.3, b[2] - 0.12; R0 = 0.42 * (b[0] - a[0])
    def rad(z):
        return max(0.03, R0 * (1 - (z - zb) / (zt - zb)) + 0.02)
    sets = {"red": ([], 0.045), "gold": ([], 0.035), "led": ([], 0.016)}
    for i in range(30):
        z = zb + 0.05 + (zt - zb - 0.15) * rg.random(); t = rg.uniform(0, 6.283); sets["red" if i % 3 else "gold"][0].append((cx + rad(z) * math.cos(t), cy + rad(z) * math.sin(t), z))
    for i in range(80):
        u = i / 79.0; z = zt - (zt - zb) * u; t = u * 6.283 * 4.5; sets["led"][0].append((cx + (rad(z) + 0.01) * math.cos(t), cy + (rad(z) + 0.01) * math.sin(t), z))
    mats = {"red": _flat("ir_apt_bauble_red", (0.55, 0.02, 0.03), 0.12, 0.35), "gold": _flat("ir_apt_bauble_gold", (0.8, 0.6, 0.2), 0.15, 0.8), "led": _flat("ir_apt_tree_led", (1.0, 0.8, 0.5), 0.5)}
    bl = mats["led"].node_tree.nodes["Principled BSDF"]; bl.inputs["Emission Color"].default_value = (1.0, 0.72, 0.38, 1.0); bl.inputs["Emission Strength"].default_value = 25.0
    for k, (pts, rr) in sets.items():
        bm = bmesh.new()
        for q in pts:
            bmesh.ops.create_icosphere(bm, subdivisions=2, radius=rr, matrix=Matrix.Translation(q))
        me = bpy.data.meshes.new(f"apt_Tree_{k}({r})"); bm.to_mesh(me); bm.free(); me.materials.append(mats[k])
        for pg in me.polygons:
            pg.use_smooth = True
        bpy.context.scene.collection.objects.link(bpy.data.objects.new(f"apt_Tree_{k}({r})", me))
    return {k: len(v[0]) for k, v in sets.items()}


def _p9_living(r, lo, hi, st, stats):
    """r4 (REF 07, library living): black floor-to-ceiling bookcase wall with books, shag rug + striped runner, sheepskin under the tree, brass reading lamp, black trolley, black-framed glass partition."""
    ra = _ra(); z0 = lo[2]; got = {}; rc = ((lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2)
    for o in [o for o in bpy.data.objects if o.name.startswith("apt_LivRug")]:
        bpy.data.objects.remove(o, do_unlink=True)
    bpy.context.view_layer.update(); obs = _obstacles(lo, hi)
    sp = _strip(r, lo, hi, obs, 3.0, 0.4, prefer="N") or _strip(r, lo, hi, obs, 2.4, 0.4, prefer="N") or _strip(r, lo, hi, obs, 1.8, 0.4, prefer="N")
    nbk = 0; books = (r"Books for Wall Shelves", r"Books for Wall Shelves", r"Faux Succulents In Low")
    if sp is not None:
        x, y, yaw, side, rect = sp; L = (rect[1] - rect[0]) if side in "SN" else (rect[3] - rect[2]); k = max(2, round(L / 1.0)); w = L / k
        for i in range(k):
            u = -L / 2 + w * (i + 0.5); px, py = (x + u, y) if side in "SN" else (x, y + u)
            bk = ra.abo("bookcase", 61 + i, px, py, z0, yaw, fit=(w, 0.42, 2.35)) or _hs(r"Milena Library Walnut|Tall Pilar Bookcase, Black", 3, px, py, z0, yaw, fit=(w, 0.44, 2.35), grow=True)
            if bk is None:
                continue
            bpy.context.view_layer.update(); a_, b_ = _bb(bk); h_ = b_[2] - a_[2]
            if 1.2 < h_ < 2.25:                                           # floor-to-ceiling: stretch the unit vertically, then stand it on the floor again
                bk.scale.z *= 2.35 / h_; bpy.context.view_layer.update(); bk.location.z += z0 - _bb(bk)[0][2]
            _recol_all(bk, (0.018, 0.018, 0.02), "ir_apt_bookcase_black", 0.45); bpy.context.view_layer.update()
            nbk += _fill_shelves(bk, rc, 11 + i, kinds=books, hmax=0.34)
        got["bookcase_items"] = nbk
        fwd = Vector((math.cos(yaw), math.sin(yaw), 0)); q = Vector((x, y, 0)) + fwd * 0.95
        RL = min(L, 2.2)                                                  # r5: the HSSD runner imported 0.7 x 0.23 m and hid under the tree: a soft striped runner (like the cork mat) instead
        rn = ra.soft(f"apt_Runner({r})", _stripe_mat("ir_apt_runner_stripe", 14.0), q.x, q.y, z0 + 0.012, *((RL, 0.8) if side in "SN" else (0.8, RL)), 0.016, yaw=0.0, seed=3, puff=0.05)
        got["runner"] = int(rn is not None)
    rg = _hs(r"Tulu Shaggy Rug - 120x160 cms, Cream", 2, rc[0] + 0.3, rc[1] - 0.2, z0, 0.0, fit=(2.4, 1.8, 0.05)); got["shag"] = int(rg is not None)
    if rg is not None:
        _set_big_slot(rg, _woven_mat("ir_apt_shag", (0.4, 0.37, 0.33), 0.5, 520.0))
    tree = next((o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith("Real_hssd(") and _in(o, lo, hi) and _bb(o)[1][2] - _bb(o)[0][2] > 1.5), None)
    if tree is not None:
        a, b = _bb(tree); sk = _hs(r"Sheared Sheepskin Rug", 3, (a[0] + b[0]) / 2, (a[1] + b[1]) / 2, z0, 0.3, fit=(1.5, 1.5, 0.05)); got["sheepskin"] = int(sk is not None)
        if sk is not None:
            _set_big_slot(sk, _woven_mat("ir_apt_sheepskin", (0.86, 0.83, 0.76), 0.25, 420.0))
        try:
            got["tree_deco"] = _tree_deco(r, a, b)
        except Exception as ex:                                       # noqa: BLE001
            import traceback; traceback.print_exc(); got["tree_deco_error"] = repr(ex)[:120]
    bpy.context.view_layer.update(); obs = _obstacles(lo, hi)
    sp = _strip(r, lo, hi, obs, 0.5, 0.5, prefer="E")
    if sp is not None:
        lp = _hs(r"FLOOR LAMP 07890, Brass", 4, sp[0], sp[1], z0, sp[2], fit=(0.4, 0.4, 1.6)); got["lamp"] = int(lp is not None)
        if lp is not None:
            _light(f"ir_apt_brasslamp_{r}", "POINT", (sp[0], sp[1], z0 + 1.45), 22, (1.0, 0.78, 0.5), r=0.08)
    bpy.context.view_layer.update(); obs = _obstacles(lo, hi)
    sp = _strip(r, lo, hi, obs, 0.7, 0.5, prefer="S")
    if sp is not None:
        tr = _hs(r"Craftsman Bar Cart", 9, sp[0], sp[1], z0, sp[2], fit=(0.7, 0.45, 0.8)); _recol_all(tr, (0.02, 0.02, 0.022), "ir_apt_trolley_black", 0.4); got["trolley"] = int(tr is not None)
    bpy.context.view_layer.update(); obs = _obstacles(lo, hi)
    sp = None
    for Lp in (1.6, 1.2):
        sp = next((q for q in (_strip(r, lo, hi, obs, Lp, 0.12, prefer=pf) for pf in "SWE") if q is not None), None)
        if sp is not None:
            _glass_partition(r, sp[0], sp[1], sp[3] in "SN", Lp, 2.2, z0); got["partition"] = 1; break
    try:
        got["door_curtain"] = _p9_doorway_curtain(r, lo, hi, mat=_floral_mat(), tag="Floral", only_one=True, skip_leaf=True)
    except Exception as ex:                                           # noqa: BLE001
        import traceback; traceback.print_exc(); got["door_curtain_error"] = repr(ex)[:120]
    stats["apt_p9_living"] = got


def _pleat_panel(name, mat, a0, a1, z0, z1, line, side, along_x, folds, depth, seed):
    import bmesh
    rg = random.Random(seed); n_u = folds * 6 + 1; n_v = 12; ph = rg.uniform(0, 6.28); bm = bmesh.new(); vs = []
    for j in range(n_v):
        z = z1 - (z1 - z0) * j / (n_v - 1); row = []
        for i in range(n_u):
            a = a0 + (a1 - a0) * i / (n_u - 1); d = side * depth / 2 * math.sin(2 * math.pi * folds * i / (n_u - 1) + ph) * (1 + 0.25 * (j / (n_v - 1)) ** 2)
            row.append(bm.verts.new((a, line + d, z) if along_x else (line + d, a, z)))
        vs.append(row)
    for j in range(n_v - 1):
        for i in range(n_u - 1):
            bm.faces.new((vs[j][i], vs[j][i + 1], vs[j + 1][i + 1], vs[j + 1][i]))
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free(); me.materials.append(mat)
    for p in me.polygons:
        p.use_smooth = True
    o = bpy.data.objects.new(name, me); bpy.context.scene.collection.objects.link(o)
    o.modifiers.new("thick", "SOLIDIFY").thickness = 0.008
    return o


def _curtains(st, stats):
    """Bedrooms (REF): sheer curtains + linen drapes either side of every window, on a thin brass rod."""
    if not st.get("curtains"):
        return
    import wall_face
    from room_planner import proc_boutique_flagship as fl
    n = 0
    lin = _woven_mat("ir_apt_curtain_linen", (0.8, 0.75, 0.64), 0.08, 120.0)
    sheer = bpy.data.materials.get("ir_apt_sheer")
    if sheer is None:
        sheer = _flat("ir_apt_sheer", (0.95, 0.94, 0.9), 0.6); b_ = sheer.node_tree.nodes["Principled BSDF"]; b_.inputs["Alpha"].default_value = 0.5; sheer["weathered"] = True
        if hasattr(sheer, "blend_method"):
            sheer.blend_method = "BLEND"
    brass = _flat("ir_apt_rod_brass", (0.72, 0.52, 0.22), 0.3, 1.0)
    for r, (lo, hi, t) in _rooms().items():
        living = t == "living-room" and ((st.get("p9_work") and _unit(STY, (lo[0] + hi[0]) / 2) == "B") or st.get("curtains_living"))          # p9 REF 07: floral curtains
        if t != "bedroom" and not living:
            continue
        zc = _zc(r, lo); lin_ = _floral_mat() if (living and st.get("p9_work")) else lin
        for w in [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith("WindowFactory(")]:
            b0, b1 = _bb(w); cx, cy = (b0[0] + b1[0]) / 2, (b0[1] + b1[1]) / 2
            along_x = (b1[0] - b0[0]) >= (b1[1] - b0[1])
            if along_x:
                if not (lo[0] - 0.2 < cx < hi[0] + 0.2 and (abs(cy - lo[1]) < 0.4 or abs(cy - hi[1]) < 0.4)):
                    continue
                sd = "S" if abs(cy - lo[1]) < 0.4 else "N"; a0, a1 = b0[0], b1[0]
            else:
                if not (lo[1] - 0.2 < cy < hi[1] + 0.2 and (abs(cx - lo[0]) < 0.4 or abs(cx - hi[0]) < 0.4)):
                    continue
                sd = "W" if abs(cx - lo[0]) < 0.4 else "E"; a0, a1 = b0[1], b1[1]
            ins = wall_face.inset(r, sd, 0.11); side = 1 if sd in "SW" else -1
            wall = {"S": lo[1], "N": hi[1], "W": lo[0], "E": hi[0]}[sd]
            line = wall + side * (ins + 0.1); zt = zc - 0.12; zb = lo[2] + 0.02
            ta, tb = a0 - 0.5, a1 + 0.5
            _pleat_panel(f"apt_DrapeL({r}|{n})", lin_, ta, a0 + 0.05, zb, zt, line, side, along_x, 5, 0.07, n)
            _pleat_panel(f"apt_DrapeR({r}|{n})", lin_, a1 - 0.05, tb, zb, zt, line, side, along_x, 5, 0.07, n + 50)
            _pleat_panel(f"apt_Sheer({r}|{n})", sheer, a0 - 0.02, a1 + 0.02, zb, zt, line - side * 0.05, side, along_x, 9, 0.04, n + 90)
            p0 = (ta - 0.03, line, zt + 0.03, tb + 0.03, line, zt + 0.03) if along_x else (line, ta - 0.03, zt + 0.03, line, tb + 0.03, zt + 0.03)
            fl.mesh_object(f"apt_Rod({r}|{n})", [(brass, [("cyl", (p0[0], p0[1], p0[2]), (p0[3], p0[4], p0[5]), 0.012, 8)])], bevel=False)
            n += 1
    stats["apt_curtains"] = n


def _p9_work(st, stats):
    if not st.get("p9_work"):
        return
    for r, (lo, hi, t) in _rooms().items():
        role = _p9_role(lo, hi)
        if t == "kitchen" and lo[0] > 20 and lo[1] < 9:
            try:
                _p9_nook(r, lo, hi, st, stats)
            except Exception as ex:                                       # noqa: BLE001
                import traceback; traceback.print_exc(); stats["apt_p9_nook_error"] = repr(ex)[:160]
            continue
        if t == "living-room" and _unit(STY, (lo[0] + hi[0]) / 2) == "B":
            try:
                _p9_living(r, lo, hi, st, stats)
            except Exception as ex:                                       # noqa: BLE001
                import traceback; traceback.print_exc(); stats["apt_p9_living_error"] = repr(ex)[:160]
            continue
        if t != "office" or role is None:
            continue
        stats[f"apt_p9_cleared_{role}"] = _p9_clear(lo, hi, extra=("AboBookcaseFactory",) if role == "study" else ())
        bpy.context.view_layer.update()
        try:
            {"craft": _p9_craft, "office": _p9_office, "study": _p9_study}[role](r, lo, hi, st, stats)
        except Exception as ex:                                           # noqa: BLE001
            import traceback; traceback.print_exc(); stats[f"apt_p9_{role}_error"] = repr(ex)[:160]




# ---------------------------------------------------------------- ratio2 (user 2026-10-26: Codex reference-match ratio >= 0.5; /bean/ir_dataset_work/reviews/ratio_gaps/floorP[789]_apt_*.md) ----------------------------------------------------------------
R2_SKIP_OBS = ("Baseboard", "Sprinkler", "apt_Downlights", "apt_BathRug", "apt_BedRug", "apt_LivRug", "apt_LivingRug", "apt_Duvet", "apt_Throw", "apt_Pillow", "apt_Cushion", "apt_Runner", "apt_Euro", "apt_Fold",
               "apt_Drape", "apt_Sheer", "apt_Rod", "apt_Mirror", "apt_RoundMirror", "apt_Wainscot", "apt_R2", "apt_Globe", "apt_Pendant", "apt_Cord")
R2_ART = r"Canyon Sunset Canvas Print|New York Picture and Frame|Red Sails"
R2_SMALLPLANT = r"Faux Succulents In Low Round Pot|stoneware planter|Purple potted plant in vase"
R2_FLOORPLANT = r"Interior Plant|coloured cordyline|Ficus alii_01|Begonia Rex"
R2_FRIDGE = r"Smeg Fridge FAB32|Smeg Fridge FAB30|American fridge freezer, small|KEW - Fridge|Caple CAFF19BK"
R2_FLOORLAMP = r"Grasshopper Floor Lamp|SIMPSON COMPLETE FLOOR LAMP|Focus Floor Lamp|Lila floor lamp|KTribe F3 Soft Floor lamp|IKEA 365\+ BRASA"


def _pil(name, rgb, cx, cy, cz, sx, sy, hz, seed, mat):
    """A real ABO pillow (rounded, soft) scaled to the footprint sx x sy (long side along the longer one), lying with its base at cz; None when the pool has none."""
    ra = _ra(); o = ra.abo("pillow", seed, cx, cy, cz, 0.0, fit=None)
    if o is None:
        return None
    bpy.context.view_layer.update(); a, b = _bb(o); d = [b[i] - a[i] for i in range(3)]
    if os.environ.get("R2DEBUG"):
        print("PIL", name, [round(v, 2) for v in d], flush=True)
    k = max(0.6, min(2.5, max(sx, sy) / max(d[0], d[1], 1e-3)))
    if d[2] * k > hz * 1.6:
        k = hz * 1.6 / d[2]
    o.scale = (o.scale[0] * k, o.scale[1] * k, o.scale[2] * k); bpy.context.view_layer.update(); a, b = _bb(o)
    if ((b[0] - a[0]) >= (b[1] - a[1])) != (sx >= sy):
        o.rotation_euler[2] += math.pi / 2; bpy.context.view_layer.update(); a, b = _bb(o)
    o.location.x += cx - (a[0] + b[0]) / 2; o.location.y += cy - (a[1] + b[1]) / 2; o.location.z += cz - a[2]
    o.name = name; _recolour(o, rgb, f"ir_apt_pil_{int(rgb[0] * 100)}_{int(rgb[1] * 100)}_{int(rgb[2] * 100)}", 0.9)
    return o


def _smooth_pillow(name, mat, cx, cy, cz, sx, sy, sz, yaw=0.0, seed=0, puff=0.6, lump=0.006):
    """A pillow / cushion as a squarish super-ellipsoid, thinner toward the seams (ra.soft's lens / octagon outline read faceted in the P8 / P9 reviews); same arguments as real_assets.soft."""
    import bmesh
    from mathutils import Matrix
    rg = random.Random(seed); bm = bmesh.new(); bmesh.ops.create_uvsphere(bm, u_segments=40, v_segments=24, radius=1.0); ph = [rg.uniform(0, 6.3) for _ in range(3)]
    def sg(t, e):
        return math.copysign(abs(t) ** e, t)
    for v in bm.verts:
        x, y, z = v.co; px, py = sg(x, 0.62), sg(y, 0.62); pz = sg(z, 0.9); edge = max(abs(px), abs(py)); taper = 1.0 - 0.55 * edge ** 3
        v.co = Vector((px * sx / 2, py * sy / 2, pz * sz / 2 * taper + lump * math.sin(px * 5 + ph[0]) * math.sin(py * 4 + ph[1])))
    if yaw:
        bmesh.ops.rotate(bm, cent=(0, 0, 0), matrix=Matrix.Rotation(yaw, 3, "Z"), verts=bm.verts)
    bmesh.ops.translate(bm, vec=(cx, cy, cz), verts=bm.verts)
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free(); me.materials.append(mat)
    for p in me.polygons:
        p.use_smooth = True
    o = bpy.data.objects.new(name, me); bpy.context.scene.collection.objects.link(o)
    return o


def _softp(st):
    return _smooth_pillow if st.get("pillow_smooth") else _ra().soft


def _t(o, kind):
    """Tag an object r2=<kind> (visibility diagnostics: which ratio2 pieces a pose can see)."""
    if o is not None:
        o["r2"] = kind
    return o


def _obs_all(lo, hi, pad=0.9):
    """_obstacles that also counts the shell's own built pieces (vanity, kitchen run ...): rects (x0, x1, y0, y1)."""
    obs = []
    for o in bpy.data.objects:
        if o.type != "MESH" or o.name.endswith(SKIP_OBJ) or o.name.startswith(R2_SKIP_OBS) or ("/" in o.name and "(" not in o.name):
            continue
        a, b = _bb(o)
        if not (b[0] > lo[0] and a[0] < hi[0] and b[1] > lo[1] and a[1] < hi[1]):
            continue
        if o.name.startswith(DOORS):
            obs.append((a[0] - pad, b[0] + pad, a[1] - pad, b[1] + pad))
        elif b[2] - a[2] > 0.25 and a[2] < 1.2 and (b[0] - a[0]) < 8 and (b[1] - a[1]) < 8:
            obs.append((a[0] - 0.05, b[0] + 0.05, a[1] - 0.05, b[1] + 0.05))
    return obs


def _drop_z(x, y, z0):
    """Height of the first surface under (x, y, z0) or None."""
    dg = bpy.context.evaluated_depsgraph_get()
    h, loc, _n, _i, _o, _m = bpy.context.scene.ray_cast(dg, Vector((x, y, z0)), Vector((0, 0, -1)))
    return loc.z if h else None


def _side_of(lo, hi, x, y):
    d = {"S": y - lo[1], "N": hi[1] - y, "W": x - lo[0], "E": hi[0] - x}
    return min(d, key=d.get)


def _yaw_in(side):
    return {"S": math.pi / 2, "N": -math.pi / 2, "W": 0.0, "E": math.pi}[side]


def _r2_art(r, lo, hi, side, along, zb, seed, wmax, hmax, rx=R2_ART):
    qx, qy, yy = _wall_pt(r, lo, hi, side, along, 0.04)
    return _t(_picture(rx, seed, qx, qy, zb, yy, wmax, hmax), "art")


def _r2_beds(st, stats):
    """Headboard art above every bed head + a small plant beside each bedside lamp (the P7 / P8 / P9 bedroom gaps: framed wall art, bedside greenery)."""
    ra = _ra(); art = pl = 0
    for k, (r, lo, hi, cx, cy, ax, hd, L, W, zt) in enumerate(_beds()):
        side = ("E" if hd > 0 else "W") if ax else ("N" if hd > 0 else "S")
        wall = {"S": lo[1], "N": hi[1], "W": lo[0], "E": hi[0]}[side]; ca = cy if ax else cx
        win = any(o.type == "MESH" and o.name.startswith(("WindowFactory(", "RollerBlind", "apt_Sheer")) and abs(((_bb(o)[0][0] + _bb(o)[1][0]) / 2 if ax else (_bb(o)[0][1] + _bb(o)[1][1]) / 2) - wall) < 0.5
                  and abs(((_bb(o)[0][1] + _bb(o)[1][1]) / 2 if ax else (_bb(o)[0][0] + _bb(o)[1][0]) / 2) - ca) < 1.4 for o in bpy.data.objects)
        try:
            if not win and _r2_art(r, lo, hi, side, cy if ax else cx, lo[2] + 1.28, 300 + k, 0.9, 0.58) is not None:
                art += 1
            elif win:                                                                           # a window on the head wall: the print goes on the nearest free strip of another wall
                g = _strip(r, lo, hi, _obs_all(lo, hi), 0.8, 0.12, prefer={"E": "N", "W": "S", "N": "W", "S": "E"}[side])
                if g is not None and _r2_art(r, lo, hi, g[3], g[0] if g[3] in "SN" else g[1], lo[2] + 1.3, 300 + k, 0.8, 0.6) is not None:
                    art += 1
        except Exception as ex:                                       # noqa: BLE001
            stats["apt_r2_art_error"] = repr(ex)[:120]
        for o in [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith(f"apt_BedLamp({r}|")]:
            a, b = _bb(o); px, py = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2; tz = a[2]
            out = (1 if py > cy else -1) if ax else (1 if px > cx else -1)
            qx, qy = (px, py + out * 0.2) if ax else (px + out * 0.2, py)
            p = ra.hssd(R2_SMALLPLANT, 310 + k, qx, qy, tz, 0.0, fit=(0.16, 0.16, 0.24))
            if p is not None:
                _t(p, "bedplant"); pl += 1
    stats["apt_r2_beds"] = {"art": art, "plants": pl}


def _r2_baths(st, stats):
    """Towel rail with two draped towels, a bath mat (when the room has none) and toiletries / a plant on the vanity top."""
    import wall_face
    from room_planner import proc_boutique_flagship as fl
    ra = _ra(); rails = mats = items = 0
    chrome = _flat("ir_apt_rail_chrome", (0.78, 0.78, 0.8), 0.2, 1.0)
    for r, (lo, hi, t) in _rooms().items():
        if t != "bathroom":
            continue
        u = st[_unit(STY, (lo[0] + hi[0]) / 2)]; z0 = lo[2]
        bpy.context.view_layer.update(); obs = _obs_all(lo, hi)
        van = next((o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith(f"apt_Vanity({r}")), None) or \
            next((o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith("HomeVanityFactory") and _in_box(o, lo, hi)), None)
        sp = _strip(r, lo, hi, obs, 0.8, 0.18, prefer="N")
        if sp is not None:
            px, py, yaw, side, rc = sp; along = px if side in "SN" else py; ax_ = side in "SN"
            ins = wall_face.inset(r, side, 0.11); sg = 1 if side in "SW" else -1
            wall = {"S": lo[1], "N": hi[1], "W": lo[0], "E": hi[0]}[side]; line = wall + sg * (ins + 0.1); zb = z0 + 1.12
            def P(s_, d_, z_):
                return (along + s_, line + sg * d_, z_) if ax_ else (line + sg * d_, along + s_, z_)
            prims = [("cyl", P(-0.34, 0, zb), P(0.34, 0, zb), 0.011, 10), ("cyl", P(-0.33, -0.1, zb), P(-0.33, 0.0, zb), 0.012, 8), ("cyl", P(0.33, -0.1, zb), P(0.33, 0.0, zb), 0.012, 8)]
            _t(fl.mesh_object(f"apt_R2Rail({r})", [(chrome, prims)], bevel=False), "rail")
            tc = [(0.93, 0.92, 0.89), tuple(u["runner"]) if isinstance(u.get("runner"), tuple) else (0.55, 0.57, 0.6)]
            for k, (s0, s1) in enumerate(((-0.31, -0.03), (0.03, 0.31))):
                m = _woven_mat(f"ir_apt_towel_{k}_{int(tc[k][0] * 100)}_{int(tc[k][2] * 100)}", tc[k], 0.05, 90.0)
                a0_, a1_ = along + s0, along + s1
                x0, x1, y0, y1 = (a0_, a1_, line - 0.03, line + 0.03) if ax_ else (line - 0.03, line + 0.03, a0_, a1_)
                tw = ra.drape(f"apt_R2Towel({r}|{k})", m, x0, x1, y0, y1, zb + 0.016, 0.5 - 0.1 * k, ax_, thick=0.02, seed=330 + k)
                _t(tw, "towel")
            rails += 1
        if van is not None:
            a, b = _bb(van); alongx = (b[0] - a[0]) >= (b[1] - a[1]); sd = _side_of(lo, hi, (a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
            ins = wall_face.inset(r, sd, 0.11); u0, u1 = (a[0], b[0]) if alongx else (a[1], b[1])
            specs = ((r"SOAP DISPENSER|Square Soap Dispenser", u0 + 0.14, (0.07, 0.07, 0.17)), (R2_SMALLPLANT, u1 - 0.14, (0.15, 0.15, 0.22)))
            for k, (rx, uu, fit) in enumerate(specs):
                qx, qy, yy = _wall_pt(r, lo, hi, sd, uu, ins * 0 + 0.17)
                tz = _drop_z(qx, qy, z0 + 1.4)
                if tz is None or tz < z0 + 0.6 or tz > z0 + 1.1:
                    continue
                o = ra.hssd(rx, 340 + k, qx, qy, tz, yy, fit=fit)
                if o is not None:
                    _t(o, "vanityitem"); items += 1
            if not any(o.name.startswith("apt_BathRug") and _in_box(o, lo, hi) for o in bpy.data.objects if o.type == "MESH") and st.get("bathmat", True):
                mx, my = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
                qx, qy, yy = _wall_pt(r, lo, hi, sd, mx if sd in "SN" else (a[1] + b[1]) / 2, 0.85)
                bm_ = ra.hssd(r"Cloud Bath Mat|White towelling bath mat|Malaga Reversible Bath Mat - 60x90|Clean Feet Bath Mat", 350, qx, qy, z0, yy, fit=(0.8, 0.55, 0.06) if alongx else (0.55, 0.8, 0.06))
                if bm_ is not None:
                    _t(bm_, "bathmat"); mats += 1
    stats["apt_r2_baths"] = {"rails": rails, "mats": mats, "items": items}


def _r2_fridge(st, r, lo, hi, n):
    """A real tall fridge-freezer: in place of the shop drinks cooler when one is left, else on a free wall strip."""
    z0 = lo[2]; x = y = yaw = None
    for o in [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith("DisplayCoolerFactory") and _in_box(o, lo, hi)]:
        a, b = _bb(o); x, y = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2; yaw = _yaw_in(_side_of(lo, hi, x, y)); bpy.data.objects.remove(o, do_unlink=True)
    if x is None:
        sp = _strip(r, lo, hi, _obs_all(lo, hi), 0.85, 0.8, prefer="N")
        if sp is None:
            return None
        x, y, yaw = sp[0], sp[1], sp[2]
    return _t(_hs(R2_FRIDGE, 360 + n, x, y, z0, yaw, fit=(0.8, 0.75, 1.85)), "fridge")


def _r2_kitchens(st, stats):
    """Domestic kitchen set-dressing: fridge, a built cooking run where a kitchen has none (p9 A), table centrepiece + fruit bowl, counter plant / canister / kettle, a runner rug."""
    import wall_face
    ra = _ra(); fr = cp = ct = rn = run = 0
    for r, (lo, hi, t) in _rooms().items():
        if t != "kitchen":
            continue
        u = st[_unit(STY, (lo[0] + hi[0]) / 2)]; z0 = lo[2]
        bpy.context.view_layer.update()
        if st.get("r2_run") and u.get("kitchen") and not any(o.name.startswith(f"apt_KitchenRun({r}") for o in bpy.data.objects):
            sp = _strip(r, lo, hi, _obs_all(lo, hi), 2.7, 0.7, prefer="N")
            if sp is not None:
                rc, side = sp[4], sp[3]; ax_ = side in "SN"
                run += _kitchen_run(st, u, r, lo, hi, side, ax_, rc[0] if ax_ else rc[2], rc[1] if ax_ else rc[3], wall_face.inset(r, side, 0.11), 7)
                bpy.context.view_layer.update()
        if _r2_fridge(st, r, lo, hi, fr) is not None:
            fr += 1
        bpy.context.view_layer.update()
        tabs = [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith(("TableDiningFactory", "Real_hssd(", "apt_Table")) and _in_box(o, lo, hi)
                and 0.62 < _bb(o)[1][2] - z0 < 1.0 and 0.7 < max(_bb(o)[1][0] - _bb(o)[0][0], _bb(o)[1][1] - _bb(o)[0][1]) < 3.2 and min(_bb(o)[1][0] - _bb(o)[0][0], _bb(o)[1][1] - _bb(o)[0][1]) > 0.6]
        if tabs:
            tb = max(tabs, key=lambda o: (_bb(o)[1][0] - _bb(o)[0][0]) * (_bb(o)[1][1] - _bb(o)[0][1])); a, b = _bb(tb); tx, ty, tz = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2, b[2]
            sx = 0.18 if (b[0] - a[0]) >= (b[1] - a[1]) else 0.0; sy = 0.18 - sx if sx == 0.0 else 0.0
            if _t(ra.hssd(r"Fairtrade dark wood fruit bowl", 370, tx - sx, ty - sy, tz, 0.0, fit=(0.3, 0.3, 0.16)), "fruitbowl") is not None:
                ct += 1
            _t(ra.hssd(r"Rose Bouquet Vase|SMALL WHITE CERAMIC BUD VASE|Purple potted plant in vase", 371, tx + sx, ty + sy, tz, 0.0, fit=(0.2, 0.2, 0.36)), "centerpiece")
        run_o = next((o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith((f"apt_KitchenRun({r}", "CafeCounterFactory")) and _in_box(o, lo, hi)), None)
        if run_o is not None:
            a, b = _bb(run_o); alongx = (b[0] - a[0]) >= (b[1] - a[1]); sd = _side_of(lo, hi, (a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
            u0, u1 = (a[0], b[0]) if alongx else (a[1], b[1]); ctz = lo[2] + 0.9 if run_o.name.startswith("apt_KitchenRun") else None
            for k, (rx, uu, fit) in enumerate(((R2_SMALLPLANT, u0 + 0.28, (0.16, 0.16, 0.24)), (r"3 PIECE SET METAL CANISTERS|Typhoon Vintage Kitchen Set|Tom Aikens knife block", u0 + 0.62, (0.2, 0.2, 0.3)),
                                               (r"Cotswold Stove Top or Hob Kettle|Prestige Deco 2 Slice Toaster|Kenwood TT720", u1 - 0.95, (0.24, 0.2, 0.26)))):
                qx, qy, yy = _wall_pt(r, lo, hi, sd, uu, 0.3)
                tz = ctz if ctz is not None else _drop_z(qx, qy, z0 + 1.6)
                if tz is None or not (z0 + 0.75 < tz < z0 + 1.2):
                    continue
                if _t(ra.hssd(rx, 380 + k, qx, qy, tz, yy, fit=fit), "counteritem") is not None:
                    cp += 1
            if u.get("runner_rug", True):
                mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2; qx, qy, yy = _wall_pt(r, lo, hi, sd, mx if alongx else my, 1.25)
                rm = _woven_mat("ir_apt_kitchen_runner", tuple(c * 0.62 for c in (u["runner"] if isinstance(u.get("runner"), tuple) else (0.5, 0.45, 0.38))), 0.12, 40.0)
                ln = max(1.6, min(2.6, (u1 - u0) - 0.4))
                _t(ra.soft(f"apt_R2KRunner({r})", rm, qx, qy, z0 + 0.006, ln if alongx else 0.62, 0.62 if alongx else ln, 0.016, seed=390, puff=0.05), "kitchenrunner"); rn += 1
    stats["apt_r2_kitchens"] = {"fridges": fr, "centerpieces": ct, "counter_items": cp, "runners": rn, "runs": run}


def _r2_living(st, stats):
    """Living rooms: a real main sofa (p8 / p9, which have none), art, a floor lamp, a floor plant, coffee-table styling; p7 gets the gallery wall + plant + styling."""
    ra = _ra(); sofas = arts = lamps = plants = style = 0
    for r, (lo, hi, t) in _rooms().items():
        if t != "living-room":
            continue
        un = _unit(STY, (lo[0] + hi[0]) / 2); u = st[un]; z0 = lo[2]
        bpy.context.view_layer.update(); obs = _obs_all(lo, hi)
        cx_, cy_ = (lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2
        cts = [o for o in bpy.data.objects if o.type == "MESH" and _in_box(o, lo, hi) and 0.3 < _bb(o)[1][2] - z0 < 0.65 and 0.5 < max(_bb(o)[1][0] - _bb(o)[0][0], _bb(o)[1][1] - _bb(o)[0][1]) < 1.7
               and not o.name.startswith(("apt_", "Real_hssd(HSSD_book")) and not o.name.endswith(SKIP_OBJ)]
        ctab = min(cts, key=lambda o: ((_bb(o)[0][0] + _bb(o)[1][0]) / 2 - cx_) ** 2 + ((_bb(o)[0][1] + _bb(o)[1][1]) / 2 - cy_) ** 2) if cts else None
        has_sofa = any(o.type == "MESH" and o.name.startswith(("AboSofaFactory", "LoveseatFactory", "Real_loungesofa")) and _in_box(o, lo, hi) for o in bpy.data.objects)
        art_done = False
        if st.get("r2_sofa") and not has_sofa:
            pos = None
            for L_ in (2.4, 2.0, 1.7):
                sp = _strip(r, lo, hi, obs, L_, 1.05, prefer="N")
                if sp is not None:
                    pos = (sp[0], sp[1], sp[2], sp[3], L_); break
            if pos is None and ctab is not None:                                              # free-standing, facing the coffee table (door swing pads cut to 0.3 m)
                obs = _obs_all(lo, hi, pad=0.0); a, b = _bb(ctab); mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
                for L_, sh, (dx, dy) in [(L_, sh, d_) for L_ in (2.0, 1.7) for sh in (0.0, 0.5, -0.5, 1.0, -1.0) for d_ in ((0, 1), (0, -1), (1, 0), (-1, 0))]:
                    if True:
                        off = (b[0] - a[0] if dx else b[1] - a[1]) / 2 + 0.2 + 0.48
                        x, y = mx + dx * off + (sh if dy else 0.0), my + dy * off + (sh if dx else 0.0)
                        rc = (x - (L_ / 2 if dy else 0.48), x + (L_ / 2 if dy else 0.48), y - (0.48 if dy else L_ / 2), y + (0.48 if dy else L_ / 2))
                        if os.environ.get("R2DEBUG"):
                            print("SOFATRY", r, L_, dx, dy, [round(v, 2) for v in rc], [(round(q[0], 2), round(q[1], 2), round(q[2], 2), round(q[3], 2)) for q in obs if rc[0] < q[1] and q[0] < rc[1] and rc[2] < q[3] and q[2] < rc[3]][:3], flush=True)
                        if lo[0] + 0.15 < rc[0] and rc[1] < hi[0] - 0.15 and lo[1] + 0.15 < rc[2] and rc[3] < hi[1] - 0.15 and not any(rc[0] < q[1] and q[0] < rc[1] and rc[2] < q[3] and q[2] < rc[3] for q in obs if not (q[0] <= a[0] - 0.04 and q[1] >= b[0] + 0.04 and q[2] <= a[1] - 0.04 and q[3] >= b[1] + 0.04)):
                            pos = (x, y, math.atan2(-dy, -dx), None, L_); break
            if pos is not None:
                x, y, yaw, side, L_ = pos
                so = ra.abo("loungesofa", 400 + sofas, x, y, z0, yaw, fit=(L_ - 0.1, 0.98, 0.92))
                if so is not None:
                    col = u.get("sofa2", (0.7, 0.66, 0.58)); _recolour(so, col, f"ir_apt_sofa2_{int(col[0] * 100)}_{int(col[1] * 100)}", 0.9); _t(so, "sofa"); sofas += 1
                    if side is not None:
                        along = x if side in "SN" else y
                        art_done = _r2_art(r, lo, hi, side, along, z0 + 1.25, 410 + sofas, 1.1, 0.7) is not None
                        arts += int(art_done)
        if not art_done and st.get("r2_sofa"):                                              # wall art on the longest free wall
            g = _strip(r, lo, hi, obs, 1.3, 0.2, prefer="N")
            if g is not None and _r2_art(r, lo, hi, g[3], g[0] if g[3] in "SN" else g[1], z0 + 1.3, 415, 1.0, 0.7) is not None:
                arts += 1
        if st.get("r2_gallery"):                                                              # p7: a gallery wall (3 frames) on the longest free wall
            g = _strip(r, lo, hi, obs, 1.8, 0.2, prefer="S")
            if g is not None:
                gx, gy, gyaw, gside, grc = g; ga = gx if gside in "SN" else gy
                for j, (du, dz) in enumerate(((-0.6, 1.35), (0.0, 1.55), (0.6, 1.3))):
                    if _r2_art(r, lo, hi, gside, ga + du, z0 + dz, 430 + j, 0.5, 0.6) is not None:
                        arts += 1
        bpy.context.view_layer.update(); obs = _obs_all(lo, hi)
        if st.get("r2_sofa") or not any(o.type == "MESH" and o.name.startswith("AboFloorlampFactory") and _in_box(o, lo, hi) for o in bpy.data.objects):                                                                 # a floor lamp in a free corner
            lp_ = _strip(r, lo, hi, obs, 0.5, 0.5, prefer="E")
            if lp_ is not None:
                lp = ra.hssd(R2_FLOORLAMP, 420 + sofas, lp_[0], lp_[1], z0, lp_[2], fit=(0.5, 0.5, 1.6))
                if lp is not None:
                    _t(lp, "floorlamp"); stats["apt_shades_glow"] = stats.get("apt_shades_glow", 0) + _glow_shade(lp, st.get("shade_emit", 8.0), True)
                    _light(f"ir_apt_r2lamp_{r}", "POINT", (lp_[0], lp_[1], z0 + 1.35), 30, (1.0, 0.78, 0.5), r=0.1); lamps += 1; obs.append(lp_[4])
        pf = _strip(r, lo, hi, obs, 0.7, 0.7, prefer="W")
        if pf is not None:
            if _t(ra.hssd(R2_FLOORPLANT, 440, pf[0], pf[1], z0, 0.0, fit=(0.6, 0.6, 1.4)), "floorplant") is not None:
                plants += 1
        if ctab is not None:
            a, b = _bb(ctab); mx, my = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
            if _t(ra.hssd(R2_SMALLPLANT, 450, mx - 0.12, my, b[2], 0.0, fit=(0.16, 0.16, 0.24)), "tablestyle") is not None:
                style += 1
            _t(ra.hssd(r"Gold pillar candle|Taleco Small Marble Candleholder|Drop Candleholder", 451, mx + 0.1, my + 0.08, b[2], 0.0, fit=(0.08, 0.08, 0.2)), "tablestyle")
            _t(ra.hssd(r"book", 452, mx + 0.02, my - 0.1, b[2], 0.4, fit=(0.24, 0.18, 0.06), size=(0.1, 0.4)), "tablestyle")
    stats["apt_r2_living"] = {"sofas": sofas, "art": arts, "lamps": lamps, "plants": plants, "styled_tables": style}


def _r2_halls(st, stats):
    """Hallways: a runner rug down the middle, two framed prints between the doors, a floor plant."""
    ra = _ra(); n = pics = pl = 0
    for r, (lo, hi, t) in _rooms().items():
        if t != "hallway":
            continue
        w, d = hi[0] - lo[0], hi[1] - lo[1]; long_x = w >= d; L = max(w, d); Wd = min(w, d); u = st[_unit(STY, (lo[0] + hi[0]) / 2)]
        if L < 4.0 or Wd < 1.1:
            continue
        z0 = lo[2]; cx, cy = (lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2
        rm = _woven_mat("ir_apt_hall_runner", tuple(c * 0.62 for c in (u["runner"] if isinstance(u.get("runner"), tuple) else (0.5, 0.45, 0.38))), 0.14, 40.0)
        rl = min(L - 1.0, 4.5); rw = min(0.9, Wd - 0.5)
        _t(ra.soft(f"apt_R2Runner({r})", rm, cx, cy, z0 + 0.006, rl if long_x else rw, rw if long_x else rl, 0.016, seed=460, puff=0.05), "hallrunner"); n += 1
        bpy.context.view_layer.update(); obs = _obs_all(lo, hi)
        for k, pref in enumerate(("W", "E")):
            g = _strip(r, lo, hi, obs, 0.9, 0.15, prefer=pref)
            if g is not None:
                gx, gy, gyaw, gside, grc = g
                if _r2_art(r, lo, hi, gside, gx if gside in "SN" else gy, z0 + 1.2, 470 + k + len(r), 0.7, 0.75) is not None:
                    pics += 1; obs.append(grc)
        pf = _strip(r, lo, hi, obs, 0.6, 0.6, prefer="N")
        if pf is not None and _t(ra.hssd(R2_FLOORPLANT, 480, pf[0], pf[1], z0, 0.0, fit=(0.55, 0.55, 1.3)), "floorplant") is not None:
            pl += 1
    stats["apt_r2_halls"] = {"runners": n, "pictures": pics, "plants": pl}


def _r2_pendants(st, stats):
    """p7: a white paper-globe pendant over each bedroom and living room (REF: paper globe / paper pendant)."""
    n = 0
    mat = _emit("ir_apt_paper_globe", (0.97, 0.94, 0.88), 2.0); cord = _flat("ir_apt_paper_cord", (0.05, 0.05, 0.05), 0.6)
    from room_planner import proc_boutique_flagship as fl
    for r, (lo, hi, t) in _rooms().items():
        if t not in ("bedroom", "living-room"):
            continue
        zc = _zc(r, lo); cx, cy = (lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2; zg = zc - 0.4
        _globe(f"apt_R2Globe({r})", cx, cy, zg, mat, r=0.2)
        fl.mesh_object(f"apt_Cord({r})", [(cord, [("cyl", (cx, cy, zc), (cx, cy, zg + 0.2), 0.004, 6)])], bevel=False)
        _light(f"ir_apt_r2globe_{r}", "POINT", (cx, cy, zg), 35, (1.0, 0.86, 0.68), r=0.2); n += 1
    stats["apt_r2_pendants"] = n


def _r2(st, stats):
    for key, fn in (("pale", _r2_pale_doors), ("beds", _r2_beds), ("baths", _r2_baths), ("kitchens", _r2_kitchens), ("kdress", _r2_kitchen_dress), ("chairs", _r2_kitchen_chairs), ("extras", _r2_extras), ("living", _r2_living), ("halls", _r2_halls), ("console", _r2_console), ("glass", _r2_glass), ("pendants", _r2_pendants), ("hall_dress", _r2_hall_dress), ("ray_bedding", _r2_ray_bedding), ("seat", _r2_seat), ("realism", _r2_realism), ("bevel", _r2_bevel)):
        if (key == "pendants" and not st.get("r2_globes")) or (key == "glass" and not st.get("r2_glass")) or (key == "pale" and not st.get("pale_doors")):
            continue
        try:
            bpy.context.view_layer.update(); fn(st, stats)
        except Exception as ex:                                       # noqa: BLE001
            import traceback; traceback.print_exc(); stats[f"apt_r2_{key}_error"] = repr(ex)[:160]


def _r2_glass(st, stats):
    """p7 unit C: the reference's glass-block feature walls (bedrooms, hall, kitchen, living): a floor-to-ceiling panel of 19 cm frosted glass blocks (blue-grey, white joints) on a free wall strip."""
    from room_planner import proc_boutique_flagship as fl
    mat = _tile("ir_apt_glassblock", (0.6, 0.78, 0.82), 0.19, (0.86, 0.88, 0.88), 0.12); n = 0
    for r, (lo, hi, t) in _rooms().items():
        if t not in ("bedroom", "hallway", "kitchen", "living-room") or lo[0] < 20:
            continue
        bpy.context.view_layer.update(); zc = _zc(r, lo); obs = _obs_all(lo, hi)
        L = 1.2 if t != "hallway" else 0.95
        sp = _strip(r, lo, hi, obs, L, 0.12, prefer="S")
        if sp is None:
            continue
        x, y, yaw, side, rc = sp; H = zc - lo[2] - 0.03
        px, py, _y = _wall_pt(r, lo, hi, side, x if side in "SN" else y, 0.045)
        sx, sy = (L, 0.07) if side in "SN" else (0.07, L)
        o = fl.mesh_object(f"apt_R2GlassBlock({r})", [(mat, [("box", px, py, lo[2] + H / 2 + 0.02, sx, sy, H)])], bevel=True)
        if o is not None:
            _t(o, "glassblock"); n += 1
    stats["apt_r2_glass"] = n


def _r2_console(st, stats):
    """Hallways: a console + a wall mirror above it on a free wall strip (the P7 / P8 reference passages carry a styled console)."""
    ra = _ra(); n = 0
    for r, (lo, hi, t) in _rooms().items():
        if t != "hallway" or max(hi[0] - lo[0], hi[1] - lo[1]) < 4.0 or min(hi[0] - lo[0], hi[1] - lo[1]) < 1.3:
            continue
        bpy.context.view_layer.update(); z0 = lo[2]; obs = _obs_all(lo, hi)
        sp = _strip(r, lo, hi, obs, 1.2, 0.42, prefer="E")
        if sp is None:
            continue
        x, y, yaw, side, rc = sp
        c = ra.abo("console", 520 + n, x, y, z0, yaw, fit=(1.1, 0.38, 0.88))
        if c is None:
            continue
        _t(c, "console"); bpy.context.view_layer.update(); a, b = _bb(c)
        along = x if side in "SN" else y
        m = _r2_art(r, lo, hi, side, along, z0 + 1.15, 530 + n, 0.7, 0.8, rx=r"Hudson Wooden Wall Mirror|Dustin Mirror|Art Deco Star mirror|Links mirror|Ren - Wall mirror")
        if m is not None:
            _t(m, "mirror")
        tz = b[2]
        _t(ra.hssd(R2_SMALLPLANT, 540 + n, x, y, tz, 0.0, fit=(0.16, 0.16, 0.24)), "consoleitem"); n += 1
    stats["apt_r2_hall_console"] = n


def _r2_pale_doors(st, stats):
    """p9: the reference doors are pale flush leaves (the generator's hotel-style leaves are brown veneer with dark grooves): the veneer / groove slots go to one pale paint, brass and card reader stay."""
    import re
    n = 0; pale = _flat("ir_apt_door_pale", (0.9, 0.89, 0.86), 0.5); groove = _flat("ir_apt_door_pale_groove", (0.82, 0.81, 0.78), 0.55)
    for o in [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith(("PanelDoorFactory", "GlassPanelDoorFactory", "LiteDoorFactory", "LouverDoorFactory"))]:
        ms = o.data.materials
        idx = [(i, m.name.lower()) for i, m in enumerate(ms) if m is not None]
        if not any(("veneer" in nm or "groove" in nm or "wood" in nm) for _i, nm in idx):
            _recol_all(o, (0.9, 0.89, 0.86), "ir_apt_door_pale", 0.5); n += 1; continue
        o.data = o.data.copy()
        for i, nm in idx:
            if "veneer" in nm or "wood" in nm:
                o.data.materials[i] = pale
            elif "groove" in nm:
                o.data.materials[i] = groove
        n += 1
    stats["apt_r2_pale_doors"] = n


def _r2_kitchen_dress(st, stats):
    """Kitchens: two framed prints on a free wall strip + a place setting (plate, cup) at each side of the dining table."""
    ra = _ra(); art = pl = 0
    for r, (lo, hi, t) in _rooms().items():
        if t != "kitchen":
            continue
        z0 = lo[2]; bpy.context.view_layer.update(); obs = _obs_all(lo, hi)
        g = _strip(r, lo, hi, obs, 1.3, 0.15, prefer="W")
        if g is not None:
            gx, gy, gyaw, gside, grc = g; ga = gx if gside in "SN" else gy
            for j, du in enumerate((-0.35, 0.35)):
                if _r2_art(r, lo, hi, gside, ga + du, z0 + 1.35, 550 + j + len(r), 0.5, 0.6) is not None:
                    art += 1
        tabs = [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith(("TableDiningFactory", "Real_hssd(", "apt_Table")) and _in_box(o, lo, hi)
                and 0.62 < _bb(o)[1][2] - z0 < 1.0 and 0.7 < max(_bb(o)[1][0] - _bb(o)[0][0], _bb(o)[1][1] - _bb(o)[0][1]) < 3.2 and min(_bb(o)[1][0] - _bb(o)[0][0], _bb(o)[1][1] - _bb(o)[0][1]) > 0.6]
        if tabs:
            tb = max(tabs, key=lambda o: (_bb(o)[1][0] - _bb(o)[0][0]) * (_bb(o)[1][1] - _bb(o)[0][1])); a, b = _bb(tb); cx, cy, tz = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2, b[2]
            w, d = b[0] - a[0], b[1] - a[1]
            for k, (dx, dy) in enumerate(((1, 0), (-1, 0), (0, 1), (0, -1))):
                px, py = cx + dx * max(0.0, w / 2 - 0.3), cy + dy * max(0.0, d / 2 - 0.3)
                if dx == 0 and dy == 0:
                    continue
                if _t(ra.lib("PlateFactory", 560 + k, px, py, tz, 0.0, 1.0), "tableware") is not None:
                    pl += 1
                if k < 2:
                    _t(ra.lib("CupFactory", 570 + k, px + 0.14 * (1 if k == 0 else -1), py + 0.12, tz, 0.0, 1.0), "tableware")
    stats["apt_r2_kitchen_dress"] = {"art": art, "plates": pl}


# ---------------------------------------------------------------- ratio2: realism (scanned PBR), bedding seat / drape, hall dressing (user 2026-10-26) ----------------------------------------------------------------
PBR_STRUCT = "/bean/ir_pbr_assets/cc0_structural_v1/polyhaven/"
TC_ENV = "/bean/ir_pbr_assets/texturecan_environment_merged_v1/texturecan/texturecan_"
FAB_SCANS = (TC_ENV + "fabric_0022", TC_ENV + "fabrics_0076", TC_ENV + "fabrics_0085")
_PBR_MEAN = {}
_LEAN = [(0.0, 0.0)]
PILL = ("apt_Pillow", "apt_Euro", "apt_Cushion")


def _img_mean(path):
    """Mean luminance of a scan map (linear), cached."""
    if path not in _PBR_MEAN:
        import numpy as np
        im = bpy.data.images.load(path, check_existing=True)
        a = np.empty(im.size[0] * im.size[1] * im.channels, np.float32); im.pixels.foreach_get(a)
        px = a.reshape(-1, im.channels)[::173, :3]
        _PBR_MEAN[path] = float((px @ np.array([0.2126, 0.7152, 0.0722], np.float32)).mean()) or 1.0
    return _PBR_MEAN[path]


def _pbr_build(m, scan, rgb, tile=2.0, contrast=0.5, rough=0.8, normal=0.7, var=0.05, ao=0.18, sheen=0.0, wrinkle=0.0, mottle=0.0):
    """Rebuild material `m` in place on a scanned PBR set: the scan's luminance (at `contrast`) under the material's own colour `rgb`, its roughness map scaled to mean `rough`, its normal map,
    a slow colour variation (+-`var`), a corner-dirt factor from an AO node (`ao`), optional cloth sheen and a duvet wrinkle bump. Returns False (material untouched) when the scan is missing."""
    d = scan + "/"
    nfile = next((f for f in ("normal_gl.png", "normal_gl.jpg") if os.path.isfile(d + f)), None)
    if not (os.path.isfile(d + "base_color.jpg") and os.path.isfile(d + "roughness.jpg") and nfile):
        return False
    m.use_nodes = True; nt = m.node_tree; nt.nodes.clear(); N, L = nt.nodes, nt.links
    out = N.new("ShaderNodeOutputMaterial"); b = N.new("ShaderNodeBsdfPrincipled"); L.new(b.outputs["BSDF"], out.inputs["Surface"])
    tc = N.new("ShaderNodeTexCoord"); mp = N.new("ShaderNodeMapping"); s_ = 1.0 / tile; mp.inputs["Scale"].default_value = (s_, s_, s_); L.new(tc.outputs["Object"], mp.inputs["Vector"])

    def tex(f, color):
        im = bpy.data.images.load(d + f, check_existing=True); im.colorspace_settings.name = "sRGB" if color else "Non-Color"
        t = N.new("ShaderNodeTexImage"); t.image = im; t.projection = "BOX"; t.projection_blend = 0.25; L.new(mp.outputs["Vector"], t.inputs["Vector"]); return t
    bc = tex("base_color.jpg", True); mean = _img_mean(d + "base_color.jpg")
    bw = N.new("ShaderNodeRGBToBW"); L.new(bc.outputs["Color"], bw.inputs["Color"])
    k_ = N.new("ShaderNodeMath"); k_.operation = "MULTIPLY_ADD"; k_.inputs[1].default_value = contrast / mean; k_.inputs[2].default_value = 1.0 - contrast; L.new(bw.outputs["Val"], k_.inputs[0])
    cc = N.new("ShaderNodeCombineColor"); [L.new(k_.outputs["Value"], cc.inputs[i]) for i in range(3)]
    mul = N.new("ShaderNodeMix"); mul.data_type = "RGBA"; mul.blend_type = "MULTIPLY"; mul.inputs["Factor"].default_value = 1.0; mul.inputs[6].default_value = (*rgb, 1); L.new(cc.outputs["Color"], mul.inputs[7])
    last = mul.outputs[2]
    if var > 0:                                                            # a slow colour drift across a surface (paint never dries uniformly)
        no = N.new("ShaderNodeTexNoise"); no.inputs["Scale"].default_value = 0.55; no.inputs["Detail"].default_value = 3.0; L.new(tc.outputs["Object"], no.inputs["Vector"])
        vr = N.new("ShaderNodeMapRange"); vr.inputs["To Min"].default_value = 1.0 - var; vr.inputs["To Max"].default_value = 1.0 + var; L.new(no.outputs["Fac"], vr.inputs["Value"])
        vc = N.new("ShaderNodeCombineColor"); [L.new(vr.outputs["Result"], vc.inputs[i]) for i in range(3)]
        mv = N.new("ShaderNodeMix"); mv.data_type = "RGBA"; mv.blend_type = "MULTIPLY"; mv.inputs["Factor"].default_value = 1.0; L.new(last, mv.inputs[6]); L.new(vc.outputs["Color"], mv.inputs[7]); last = mv.outputs[2]
    if mottle > 0:                                                         # medium-scale mottling (~0.3 m patches, +-mottle) so a painted wall does not read as one flat colour at 512 px
        n2 = N.new("ShaderNodeTexNoise"); n2.inputs["Scale"].default_value = 3.2; n2.inputs["Detail"].default_value = 6.0; n2.inputs["Roughness"].default_value = 0.65; L.new(tc.outputs["Object"], n2.inputs["Vector"])
        r2 = N.new("ShaderNodeMapRange"); r2.inputs["To Min"].default_value = 1.0 - mottle; r2.inputs["To Max"].default_value = 1.0 + mottle; L.new(n2.outputs["Fac"], r2.inputs["Value"])
        c2 = N.new("ShaderNodeCombineColor"); [L.new(r2.outputs["Result"], c2.inputs[i]) for i in range(3)]
        m2 = N.new("ShaderNodeMix"); m2.data_type = "RGBA"; m2.blend_type = "MULTIPLY"; m2.inputs["Factor"].default_value = 1.0; L.new(last, m2.inputs[6]); L.new(c2.outputs["Color"], m2.inputs[7]); last = m2.outputs[2]
    if ao > 0:                                                             # dirt in the corners, under doors, along skirting
        ak = N.new("ShaderNodeAmbientOcclusion"); ak.inputs["Distance"].default_value = 0.3; ak.samples = 6
        ar = N.new("ShaderNodeMapRange"); ar.inputs["To Min"].default_value = 1.0 - ao; ar.inputs["To Max"].default_value = 1.0; L.new(ak.outputs["AO"], ar.inputs["Value"])
        ac = N.new("ShaderNodeCombineColor"); [L.new(ar.outputs["Result"], ac.inputs[i]) for i in range(3)]
        ma = N.new("ShaderNodeMix"); ma.data_type = "RGBA"; ma.blend_type = "MULTIPLY"; ma.inputs["Factor"].default_value = 1.0; L.new(last, ma.inputs[6]); L.new(ac.outputs["Color"], ma.inputs[7]); last = ma.outputs[2]
    L.new(last, b.inputs["Base Color"])
    rt = tex("roughness.jpg", False); rm = N.new("ShaderNodeMath"); rm.operation = "MULTIPLY"; rm.use_clamp = True; rm.inputs[1].default_value = rough / _img_mean(d + "roughness.jpg"); L.new(rt.outputs["Color"], rm.inputs[0]); L.new(rm.outputs["Value"], b.inputs["Roughness"])
    nm = tex(nfile, False); nn = N.new("ShaderNodeNormalMap"); nn.inputs["Strength"].default_value = normal; L.new(nm.outputs["Color"], nn.inputs["Color"]); nrm = nn.outputs["Normal"]
    if wrinkle > 0:                                                        # duvet: broad soft creases over the weave
        wn = N.new("ShaderNodeTexNoise"); wn.inputs["Scale"].default_value = 5.5; wn.inputs["Detail"].default_value = 4.0; wn.inputs["Roughness"].default_value = 0.6; L.new(tc.outputs["Object"], wn.inputs["Vector"])
        bu = N.new("ShaderNodeBump"); bu.inputs["Strength"].default_value = wrinkle; bu.inputs["Distance"].default_value = 0.012; L.new(wn.outputs["Fac"], bu.inputs["Height"]); L.new(nrm, bu.inputs["Normal"]); nrm = bu.outputs["Normal"]
    L.new(nrm, b.inputs["Normal"])
    if sheen > 0:
        b.inputs["Sheen Weight"].default_value = sheen; b.inputs["Sheen Roughness"].default_value = 0.45
    m["apt_pbr"] = os.path.basename(scan)
    return True


R2_FABRIC = ("ir_apt_duvet_", "ir_apt_throw", "ir_apt_runner", "ir_apt_euro_", "ir_apt_cuff_", "ir_apt_pillow", "ir_apt_pil_", "ir_apt_cushion_", "ir_apt_curtain_linen", "ir_apt_sofa2_", "ir_apt_sofa_", "ir_apt_arm_",
             "ir_apt_rug_", "ir_apt_bathrug", "ir_apt_hall_runner", "ir_apt_kitchen_runner", "ir_apt_towel_", "ir_apt_mat_")


def _r2_realism(st, stats):
    """Scanned PBR for the big surfaces (plaster walls, grey-plank floors, woven fabrics with sheen, a wrinkled duvet) in place of the flat / procedural materials; the shell's colours stay, the scan supplies the
    luminance detail, roughness and normal. Materials are rebuilt in place, so every user of them (walls, floors, bedding, curtains) picks it up."""
    import zlib
    cnt = {"walls": 0, "floors": 0, "fabrics": 0, "missing": 0}; used = set()
    for m in list(bpy.data.materials):
        rgb = m.get("apt_rgb"); nm = m.name
        if rgb is None or m.get("apt_pbr"):
            continue
        rgb = tuple(rgb)
        if nm.startswith("ir_apt_paint_"):
            dark = sum(rgb) / 3 < 0.3; scan = PBR_STRUCT + ("grey_plaster" if dark else "plastered_wall"); ok = _pbr_build(m, scan, rgb, tile=1.0 if dark else 1.4, contrast=0.75, rough=0.85, normal=1.1, var=0.035, ao=0.26, mottle=0.03); k = "walls"
        elif nm.startswith("ir_apt_plank_"):
            scan = PBR_STRUCT + "wood_planks_grey"; ok = _pbr_build(m, scan, rgb, tile=1.5, contrast=0.8, rough=0.5, normal=1.0, var=0.06, ao=0.28); k = "floors"
        elif nm.startswith(R2_FABRIC):
            scan = FAB_SCANS[zlib.crc32(nm.encode()) % len(FAB_SCANS)]; ok = _pbr_build(m, scan, rgb, tile=0.5, contrast=0.35, rough=0.92, normal=0.9, var=0.0, ao=0.1, sheen=0.4, wrinkle=0.5 if nm.startswith("ir_apt_duvet_") else 0.0); k = "fabrics"
        else:
            continue
        if ok:
            cnt[k] += 1; used.add(os.path.basename(scan))
        else:
            cnt["missing"] += 1
    stats["apt_r2_realism"] = {**cnt, "scans": sorted(used)}


def _r2_bevel(st, stats):
    """2-3 mm bevels on furniture / door / skirting edges (a razor edge is the first thing that reads CG): a Bevel modifier on every placed asset and door / skirting mesh under 40 k faces."""
    n = 0
    for o in bpy.data.objects:
        if o.type != "MESH" or o.name.endswith(SKIP_OBJ) or o.modifiers.get("r2bev") is not None:
            continue
        if not o.name.startswith(("Real_", "Baseboard", "DoorCasing", "PanelDoor", "LiteDoor", "LouverDoor", "GlassPanelDoor", "apt_Wardrobe", "apt_Vanity", "apt_Kitchen", "apt_R2Console")) or len(o.data.polygons) > 40000:
            continue
        a, b = _bb(o)
        if max(b[i] - a[i] for i in range(3)) < 0.25:
            continue
        md = o.modifiers.new("r2bev", "BEVEL"); md.width = 0.0025; md.segments = 2; md.limit_method = "ANGLE"; md.angle_limit = math.radians(35); n += 1
    stats["apt_r2_bevels"] = n


def _surf_trees(objs):
    from mathutils.bvhtree import BVHTree
    dg = bpy.context.evaluated_depsgraph_get(); out = []
    for o in objs:
        try:
            # pkg_h_apt: all callers cast world-space rays; FromObject is local.
            evaluated = o.evaluated_get(dg)
            mesh = evaluated.to_mesh()
            try:
                matrix = evaluated.matrix_world
                vertices = [matrix @ v.co for v in mesh.vertices]
                polygons = [tuple(p.vertices) for p in mesh.polygons]
                out.append(BVHTree.FromPolygons(vertices, polygons))
            finally:
                evaluated.to_mesh_clear()
        except Exception:                                             # noqa: BLE001
            pass
    return out


def _surf_z(trees, x, y, z0):
    best = None
    for t in trees:
        h = t.ray_cast(Vector((x, y, z0)), Vector((0, 0, -1)), 3.0)
        if h[0] is not None and (best is None or h[0].z > best):
            best = h[0].z
    return best


def _bed_surface_objs(r, lo, hi, skip=PILL):
    out = []
    for o in bpy.data.objects:
        if o.type != "MESH" or o.name.startswith(skip):
            continue
        if o.name.startswith((f"apt_Duvet({r})", f"apt_Throw({r})", f"apt_Fold({r})", f"apt_Runner({r})", f"apt_SpareBed({r})")) or (o.name.startswith("MattressFactory") and _in_box(o, lo, hi)):
            out.append(o)
    return out


def _cf(o, st, ax, ztop, W, r, lo, hi, cx, cy):
    """Conform a draped cloth to what lies under it: every vertex of the top region sits 1 cm over the surface found by a ray straight down; the hanging sides keep their drop profile from there."""
    if o is None or not st.get("cloth_soft"):
        return o
    bpy.context.view_layer.update()
    trees = _surf_trees([q for q in _bed_surface_objs(r, lo, hi) if q is not o]); half = max(0.2, W / 2 - 0.03)
    if not trees:
        return o
    for v in o.data.vertices:
        x, y, z = v.co.x, v.co.y, v.co.z
        a = (y - cy) if ax else (x - cx); ac = max(-half, min(half, a)); px, py = (x, cy + ac) if ax else (cx + ac, y)
        s = _surf_z(trees, px, py, ztop + 0.5)
        if s is not None:
            rel = z - ztop; u_ = x if ax else y
            v.co.z = s + 0.012 + rel + 0.011 * math.sin(u_ * 13.0 + 1.1) * math.sin(a * 5.0 + 0.4) + 0.006 * math.sin(u_ * 31.0) * math.cos(a * 9.0)      # soft folds over the weave
            if abs(a) > half - 0.08:                                       # a rounded shoulder where the cloth turns over the edge, a soft belly and a lightly wavy hem below it
                v.co.z -= 0.025 * min(1.0, (abs(a) - (half - 0.08)) / 0.08) ** 2
            if rel < -0.02:
                sg_ = 1.0 if a > 0 else -1.0; fl_ = 0.035 * min(1.0, -rel / 0.2); hem = 0.014 * math.sin(u_ * 19.0 + 1.7) * min(1.0, -rel / 0.2)
                if ax:
                    v.co.y += sg_ * fl_
                else:
                    v.co.x += sg_ * fl_
                v.co.z += hem
    o.data.update()
    return o


def _smooth_pillow(name, mat, cx, cy, cz, sx, sy, sz, yaw=0.0, seed=0, puff=0.6, lump=0.006):
    """Real pillows: flat rectangles with pinched corners and a thin sewn seam all round, two inflated faces: a bed pillow is 50 x 70 cm (12-14 cm at the middle), a euro 55 x 55, a cushion 45 x 45, all
    leaning back toward the headboard. Same arguments as real_assets.soft; the pillowcase weave comes from the fabric scan on the material."""
    import bmesh
    from mathutils import Matrix
    lean = 0.0; kind = "pillow"
    if name.startswith("apt_Euro"):
        sx = sy = 0.55; sz = 0.15; lean = 0.5; kind = "euro"
    elif name.startswith("apt_Pillow"):
        a_, b_ = (0.7, 0.5); sx, sy = (a_, b_) if sx >= sy else (b_, a_); sz = 0.13; lean = 0.22
    elif name.startswith("apt_Cushion"):
        sx = sy = 0.45; sz = 0.11; lean = 0.38; kind = "cushion"
    rg = random.Random(seed); bm = bmesh.new(); N = 34; ph = [rg.uniform(0, 6.3) for _ in range(3)]

    def t_(u, v):                                                           # half thickness at (u, v) in -1..1: full in the middle, pinched toward the corners, a 6 mm seam at the border
        k = max(0.0, (1.0 - abs(u) ** 3.4)) * max(0.0, (1.0 - abs(v) ** 3.4))
        return max(0.006, sz / 2 * k ** 0.6 + 0.006)
    top = []; bot = []
    for j in range(N + 1):
        rt = []; rb = []
        for i in range(N + 1):
            u = -1 + 2 * i / N; v = -1 + 2 * j / N
            # pull the corners in a little (a pillow is not a perfect rectangle): the corner of a stuffed case sits ~4 % inside
            cs = 1.0 - 0.05 * (abs(u) * abs(v)) ** 2
            x_, y_ = u * sx / 2 * cs, v * sy / 2 * cs; tz = t_(u, v)
            w = lump * math.sin(u * 4 + ph[0]) * math.sin(v * 3 + ph[1]) + 0.004 * math.sin((abs(u) + abs(v)) * 9 + ph[2]) * (abs(u) * abs(v))      # soft creases running to the corners
            rt.append(bm.verts.new((x_, y_, tz + w))); rb.append(bm.verts.new((x_, y_, -tz + w * 0.5)) if 0 < i < N and 0 < j < N else rt[-1])
        top.append(rt); bot.append(rb)
    for j in range(N):
        for i in range(N):
            bm.faces.new((top[j][i], top[j][i + 1], top[j + 1][i + 1], top[j + 1][i]))
            f = (bot[j][i], bot[j + 1][i], bot[j + 1][i + 1], bot[j][i + 1])
            if len(set(f)) == 4:
                bm.faces.new(f)
            elif len(set(f)) == 3:
                try:
                    bm.faces.new(tuple(dict.fromkeys(f)))
                except ValueError:
                    pass
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    if lean:
        dx, dy = _LEAN[0]
        if dx or dy:
            ax_ = Vector((-dy, dx, 0.0)).normalized(); R = Matrix.Rotation(lean, 3, ax_)
            if (R @ Vector((0, 0, 1))).dot(Vector((dx, dy, 0))) < 0:
                R = Matrix.Rotation(-lean, 3, ax_)
            bmesh.ops.rotate(bm, cent=(0, 0, 0), matrix=R, verts=bm.verts)
    if yaw:
        bmesh.ops.rotate(bm, cent=(0, 0, 0), matrix=Matrix.Rotation(yaw, 3, "Z"), verts=bm.verts)
    bmesh.ops.translate(bm, vec=(cx, cy, cz), verts=bm.verts)
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free(); me.materials.append(mat)
    for p in me.polygons:
        p.use_smooth = True
    o = bpy.data.objects.new(name, me); bpy.context.scene.collection.objects.link(o)
    sb = o.modifiers.new("sub", "SUBSURF"); sb.levels = 1; sb.render_levels = 2
    return o


def _softp(st):
    return _smooth_pillow if st.get("pillow_smooth") else _ra().soft


def _r2_ray_bedding(st, stats):
    """pkg_h_apt: replace soft bedding transactionally with ray-supported strips."""
    if not st.get('cloth_soft'):
        return
    from bedding_cloth import drape_strip
    records = []; failures = []
    bpy.context.view_layer.update()
    for r, lo, hi, cx, cy, ax, hd, length, width, zt in _beds():
        base = [o for o in bpy.data.objects if o.type == 'MESH' and
                ((o.name.startswith('MattressFactory') and _in_box(o, lo, hi)) or
                 o.name == f'apt_SpareBed({r})')]
        if not base:
            failures.append(f'{r}: no mattress support'); continue
        trees = _surf_trees(base)
        old = [o for o in bpy.data.objects if o.type == 'MESH' and
               any(o.name == f'apt_{kind}({r})' for kind in ('Duvet','Throw','Runner','Fold'))]
        materials = {o.name.split('(')[0]: o.data.materials[0] for o in old if o.data.materials}
        created = []
        # Exclude bed frame overhangs/headboard; probe the actual middle surface.
        half = width / 2 - .08
        class Support:
            half_span = half
            def __init__(self, support, offset):
                self.support = support; self.offset = offset
            def point(self, across, along, z_offset):
                a = along + self.offset
                return Vector((cx + hd*a, cy + across, z_offset) if ax else
                              (cx + across, cy + hd*a, z_offset))
            def __call__(self, across, along):
                p = self.point(across, along, 0)
                z = _surf_z(self.support, p.x, p.y, zt + .15)
                return Vector((p.x, p.y, z)) if z is not None else None
        try:
            specs = [('Duvet', max(.65, length-.55), -.12, min(.32, zt-lo[2]-.08)),
                     ('Throw', .48, -length/2+.48, .23),
                     ('Fold', .18, length/2-.58, .08),
                     ('Runner', .32, -length/2+.92, .19)]
            for kind, span, offset, hang in specs:
                mat = materials.get('apt_'+kind)
                if mat is None:
                    continue
                callback = Support(trees, offset)
                obj = drape_strip(callback, span, 2*half+2*hang+.02, hang)
                created.append(obj); obj.data.materials.append(mat)
                obj['pkg_h_room'] = r; obj['pkg_h_kind'] = kind
                # Verify against precisely the surfaces used for this layer.
                gaps = []
                for index in obj['contact_vertices']:
                    p = obj.data.vertices[index].co
                    z = _surf_z(trees, p.x, p.y, zt+.15)
                    if z is None:
                        raise ValueError('missing verification support')
                    gaps.append(p.z-z)
                if not gaps or min(gaps) < .001 or max(gaps) > .007:
                    raise ValueError(f'{kind} support gap outside 1..7 mm')
                obj['pkg_h_gap_max_m'] = max(gaps)
                bpy.context.view_layer.update()
                trees = _surf_trees(base + created)
            if not created:
                raise ValueError('no existing cloth materials')
        except Exception as ex:
            for obj in created:
                bpy.data.objects.remove(obj, do_unlink=True)
            failures.append(f'{r}: {ex}'); continue
        for obj in old:
            bpy.data.objects.remove(obj, do_unlink=True)
        for obj in created:
            obj.name = f"apt_{obj['pkg_h_kind']}({r})"
        # Re-anchor pillow rows inside the mattress, clear of the headboard.
        # A headboard is also a ray surface: merely seating the old rear row
        # can certify contact on its top instead of on the mattress.
        from mathutils import Matrix
        for pillow in [o for o in bpy.data.objects if o.type == 'MESH' and
                       o.name.startswith(PILL) and f'({r}|' in o.name]:
            a, b = _bb(pillow)
            px, py = (a[0]+b[0])/2, (a[1]+b[1])/2
            index = int(pillow.name.split('|')[-1].split(')')[0])
            cross = (-1 if index % 2 == 0 else 1) * width / 4
            along = length/2 - (1.0 if pillow.name.startswith('apt_Cushion') else .75 if pillow.name.startswith('apt_Pillow') else .55)
            target = Vector((cx+hd*along, cy+cross, zt+.18) if ax else
                            (cx+cross, cy+hd*along, zt+.18))
            centre = Vector((px,py,(a[2]+b[2])/2))
            turn = math.pi/2 if pillow.name.startswith('apt_Pillow') and ((b[0]-a[0] >= b[1]-a[1]) == ax) else 0
            pillow.matrix_world = (Matrix.Translation(target) @
                                   Matrix.Rotation(turn,4,'Z') @
                                   Matrix.Translation(-centre) @ pillow.matrix_world)
        bpy.context.view_layer.update()
        records.append({'room': r, 'layers': len(created),
                        'max_gap_m': max(o['pkg_h_gap_max_m'] for o in created)})
    stats['pkg_h_ray_bedding'] = {'beds': records, 'fail': failures}


def _r2_seat(st, stats):
    """Seat every pillow / cushion on what is under it: its lowest vertices are ray-cast onto the mattress / duvet / throw (a BVH of just the bed's own surfaces) and the piece is moved until its lowest point is 4 mm over
    the surface; the result is verified (gap between the pillow's bottom and the surface < 1 cm) and reported."""
    bpy.context.view_layer.update(); rooms = _rooms(); n = ok = 0; fails = []; worst = 0.0
    for r, (lo, hi, t) in rooms.items():
        if t != "bedroom":
            continue
        pills = [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith(PILL) and f"({r}|" in o.name]
        if not pills:
            continue
        trees = _surf_trees(_bed_surface_objs(r, lo, hi))
        if not trees:
            continue
        for o in dict.fromkeys(pills):
            mw = o.matrix_world; vs = sorted((mw @ v.co for v in o.data.vertices), key=lambda p: p.z)[:80]; n += 1; gap = None
            for _it in range(3):
                gs = []
                for p in vs:
                    s = _surf_z(trees, p.x, p.y, p.z + 0.6)
                    if s is not None and -0.3 < p.z - s < 0.6:
                        gs.append(p.z - s)
                if not gs and _it == 0:                                    # the lowest vertices hang past the mattress end: widen to every vertex
                    vs = sorted((mw @ v.co for v in o.data.vertices), key=lambda p_: p_.z)
                    for p in vs[::6]:
                        s = _surf_z(trees, p.x, p.y, p.z + 0.6)
                        if s is not None and -0.3 < p.z - s < 0.6:
                            gs.append(p.z - s)
                if not gs:
                    break
                gap = min(gs); dz = gap - 0.004
                if abs(dz) < 0.0005:
                    break
                o.location.z -= dz; vs = [p - Vector((0, 0, dz)) for p in vs]
            if gap is None:
                fails.append(o.name); continue
            gs2 = [p.z - s for p in vs for s in [_surf_z(trees, p.x, p.y, p.z + 0.6)] if s is not None and -0.3 < p.z - s < 0.6]
            g = min(gs2) if gs2 else gap; worst = max(worst, abs(g))
            if abs(g) < 0.01:
                ok += 1
            else:
                fails.append(f"{o.name}:{g:.3f}")
    stats["apt_r2_pillow_gap"] = {"pillows": n, "pass": ok, "fail": fails[:12], "worst_cm": round(worst * 100, 2)}
    bpy.context.view_layer.update()


def _r2_hall_dress(st, stats):
    """Corridor / unit-hall dressing from the references: a brass number plate beside every door, a door mat at each entry, wall sconces between the doors, a shoe rack at some doors, a bench, a print series, plants,
    and at the lift / stair core an exit sign + a fire extinguisher."""
    from room_planner import proc_boutique_flagship as fl
    ra = _ra(); brass = _flat("ir_apt_brass_plate", (0.72, 0.52, 0.22), 0.3, 1.0); plates = mats = sconces = racks = misc = 0
    matm = _woven_mat("ir_apt_mat_coir", (0.36, 0.28, 0.18), 0.2, 60.0)
    for r, (lo, hi, t) in _rooms().items():
        if t != "hallway":
            continue
        W_, D_ = hi[0] - lo[0], hi[1] - lo[1]; long_x = W_ >= D_; Lh = max(W_, D_); Wh = min(W_, D_); z0 = lo[2]
        if Lh < 2.5:
            continue
        bpy.context.view_layer.update()
        cas = [c for c in bpy.data.objects if c.type == "MESH" and c.name.startswith("DoorCasingFactory") and lo[0] - 0.4 < (_bb(c)[0][0] + _bb(c)[1][0]) / 2 < hi[0] + 0.4 and lo[1] - 0.4 < (_bb(c)[0][1] + _bb(c)[1][1]) / 2 < hi[1] + 0.4]
        per_side = {}
        for k, c in enumerate(cas):
            a, b = _bb(c); cx_, cy_ = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2; side = _side_of(lo, hi, cx_, cy_)
            if side in "SN" and (b[0] - a[0]) < 0.5 or side in "WE" and (b[1] - a[1]) < 0.5:
                continue
            al = cx_ if side in "SN" else cy_; wid = (b[0] - a[0]) if side in "SN" else (b[1] - a[1]); per_side.setdefault(side, []).append((al, wid))
            px, py, yy = _wall_pt(r, lo, hi, side, al + (wid / 2 + 0.2), 0.012)
            pl = fl.mesh_object(f"apt_R2Plate({r}|{k})", [(brass, [("box", px, py, z0 + 1.55, *((0.1, 0.012, 0.05) if side in "SN" else (0.012, 0.1, 0.05)))])], bevel=True)
            if pl is not None:
                _t(pl, "plate"); plates += 1
            mx_, my_, _y = _wall_pt(r, lo, hi, side, al, 0.42)
            if Wh > 1.8:
                mt = ra.soft(f"apt_R2Mat({r}|{k})", matm, mx_, my_, z0 + 0.008, *((0.8, 0.5) if side in "SN" else (0.5, 0.8)), 0.014, seed=600 + k, puff=0.05)
                _t(mt, "doormat"); mats += 1
        for side, lst in per_side.items():
            lst.sort()
            for (a1, w1), (a2, w2) in zip(lst, lst[1:]):
                gap = (a2 - w2 / 2) - (a1 + w1 / 2)
                if gap > 1.2:
                    qx, qy, yy = _wall_pt(r, lo, hi, side, (a1 + w1 / 2 + a2 - w2 / 2) / 2, 0.06)
                    sc_ = _hs(r"IC C/W1 Sconce|Type 75 Mini Wall Light|Radius' Double Spot wall ligh|Currey & Company Malvasia Wall", 620 + sconces, qx, qy, z0 + 1.75, yy, fit=(0.22, 0.2, 0.3))
                    if sc_ is not None:
                        _t(sc_, "sconce"); sconces += 1; _light(f"ir_apt_sconce_{r}_{sconces}", "POINT", (qx + math.cos(yy) * 0.12, qy + math.sin(yy) * 0.12, z0 + 1.9), 14, (1.0, 0.78, 0.5), r=0.06)
        bpy.context.view_layer.update(); obs = _obs_all(lo, hi)
        if Wh > 1.3:
            for k in range(2 if Lh > 8 else 1):
                sp = _strip(r, lo, hi, obs, 0.85, 0.35, prefer="W" if k == 0 else "E")
                if sp is not None:
                    o = ra.hssd(r"Chrome Shoe Rack|Telescopic Shoe Rack|Sko Shoe Rack|Cedar Shoe Rack", 630 + k, sp[0], sp[1], z0, sp[2], fit=(0.85, 0.34, 0.5))
                    if o is not None:
                        _t(o, "shoerack"); racks += 1; obs.append(sp[4])
            if Lh > 8:                                                          # the shared corridor: a bench, more prints
                sp = _strip(r, lo, hi, obs, 1.5, 0.5, prefer="N")
                if sp is not None:
                    o = ra.abo("bench", 640, sp[0], sp[1], z0, sp[2], fit=(1.5, 0.45, 0.5))
                    if o is not None:
                        _t(o, "bench"); misc += 1; obs.append(sp[4])
                        _t(ra.hssd(R2_FLOORPLANT, 641, sp[0] + (1.1 if sp[3] in "SN" else 0), sp[1] + (1.1 if sp[3] in "WE" else 0), z0, 0.0, fit=(0.55, 0.55, 1.3)), "floorplant")
                for k in range(4):
                    g = _strip(r, lo, hi, obs, 0.8, 0.15, prefer="S" if k % 2 else "N")
                    if g is not None:
                        if _r2_art(r, lo, hi, g[3], g[0] if g[3] in "SN" else g[1], z0 + 1.25, 650 + k, 0.6, 0.7) is not None:
                            misc += 1; obs.append(g[4])
                # the lift / stair core end: exit sign over it + an extinguisher on the wall
                endx = (lo[0] + 0.5, hi[0] - 0.5) if long_x else None
                if long_x:
                    for en in (hi[0], lo[0]):
                        px, py, yy = _wall_pt(r, lo, hi, "E" if en == hi[0] else "W", (lo[1] + hi[1]) / 2, 0.04)
                        sg_ = _picture(r"exit sign", 660, px, py, z0 + 2.05, yy, 0.5, 0.25)
                        if sg_ is not None:
                            _t(sg_, "exitsign"); misc += 1
                            _light(f"ir_apt_exit_{r}_{int(en)}", "POINT", (px + math.cos(yy) * 0.1, py + math.sin(yy) * 0.1, z0 + 2.15), 6, (0.5, 1.0, 0.6), r=0.05)
                            ex_, ey_, eyy = _wall_pt(r, lo, hi, "E" if en == hi[0] else "W", (lo[1] + hi[1]) / 2 + 0.9, 0.12)
                            o = ra.hssd(r"Korean Fire Extinguisher 01", 661, ex_, ey_, z0 + 0.3, eyy, fit=(0.25, 0.25, 0.5))
                            if o is not None:
                                _t(o, "extinguisher"); misc += 1
                            break
    stats["apt_r2_hall_dress"] = {"plates": plates, "mats": mats, "sconces": sconces, "shoeracks": racks, "misc": misc}


def _spare_top(o, lo):
    """Top of a real bed's mattress: a ray straight down at the middle of its footprint (the old constant 0.52 m floated the bedding over a 0.76 m platform bed)."""
    try:
        a, b = _bb(o); tr = _surf_trees([o]); z = _surf_z(tr, (a[0] + b[0]) / 2, (a[1] + b[1]) / 2, b[2] + 0.2) if tr else None
    except Exception:                                                  # noqa: BLE001
        z = None
    return z if z is not None else lo[2] + 0.52


def _roll_fold(name, mat, cc, ax, W, zt, r, lo, hi):
    try:
        return _roll_fold_(name, mat, cc, ax, W, zt, r, lo, hi)
    except Exception as ex:                                            # noqa: BLE001 -- a failed cuff must not take the whole layers part with it
        import traceback; traceback.print_exc(); return None


def _roll_fold_(name, mat, cc, ax, W, zt, r, lo, hi):
    """The folded-back duvet cuff at the head of a bed: a rounded roll (~11 cm across) lying over the duvet across the full width, resting on whatever is under it (ray-cast), in place of a hanging cloth strip."""
    import bmesh
    bpy.context.view_layer.update(); trees = _surf_trees(_bed_surface_objs(r, lo, hi))
    s = _surf_z(trees, cc[0], cc[1], zt + 0.8) if trees else None
    base = (s if s is not None else zt + 0.03) + 0.004; rad = 0.055; length = W - 0.04
    bm = bmesh.new(); NU, NV = 36, 14; rg = random.Random(hash(name) & 0xffff)
    rows = []
    for i in range(NU + 1):
        u = -length / 2 + length * i / NU; e = min(1.0, (length / 2 - abs(u)) / 0.05 + 0.15)                      # the ends round off
        row = []
        for j in range(NV):
            th = 2 * math.pi * j / NV; rr = rad * (0.4 + 0.6 * e) * (1.0 + 0.06 * math.sin(u * 14 + th * 2))
            cx_, cz_ = rr * math.cos(th) * 1.5, rr * math.sin(th) * (1.0 if math.sin(th) > 0 else 0.45)           # wider than tall, flat underneath
            row.append(bm.verts.new((cx_, u, cz_) if ax else (u, cx_, cz_)))
        rows.append(row)
    for i in range(NU):
        for j in range(NV):
            bm.faces.new((rows[i][j], rows[i + 1][j], rows[i + 1][(j + 1) % NV], rows[i][(j + 1) % NV]))
    c0 = bm.verts.new((0, -length / 2, 0) if ax else (-length / 2, 0, 0)); c1 = bm.verts.new((0, length / 2, 0) if ax else (length / 2, 0, 0))
    for j in range(NV):
        bm.faces.new((c0, rows[0][(j + 1) % NV], rows[0][j])); bm.faces.new((c1, rows[NU][j], rows[NU][(j + 1) % NV]))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:]); bmesh.ops.translate(bm, vec=(cc[0], cc[1], base + rad * 0.45), verts=bm.verts)
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free(); me.materials.append(mat)
    for p_ in me.polygons:
        p_.use_smooth = True
    o = bpy.data.objects.new(name, me); bpy.context.scene.collection.objects.link(o)
    return o


# ---------------------------------------------------------------- ratio2 batch 2: kitchen chairs, side-wall art, floor lamps, footstool ----------------------------------------------------------------
R2_CHAIRN = ("ChairFactory", "AboCafechair", "Real_deskchair", "BarStool", "StoolFactory", "CounterStool", "AboChair", "AboStool")


def _r2_kitchen_chairs(st, stats):
    """The dining table gets four matching chairs (p7: the layout's two or three are completed; p8 / p9: the mismatched loose seats are replaced by one coherent set)."""
    ra = _ra(); placed = removed = 0
    for r, (lo, hi, t) in _rooms().items():
        u = st[_unit(STY, (lo[0] + hi[0]) / 2)]
        if t != "kitchen" or u.get("dining") == "nook" or not st.get("r2_chairs"):
            continue
        z0 = lo[2]; bpy.context.view_layer.update()
        tabs = [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith(("TableDiningFactory", "Real_hssd(", "apt_Table")) and _in_box(o, lo, hi)
                and 0.62 < _bb(o)[1][2] - z0 < 1.0 and 0.7 < max(_bb(o)[1][0] - _bb(o)[0][0], _bb(o)[1][1] - _bb(o)[0][1]) < 3.2 and min(_bb(o)[1][0] - _bb(o)[0][0], _bb(o)[1][1] - _bb(o)[0][1]) > 0.6]
        if not tabs:
            continue
        if st.get("r2_chairs") == "coherent" and any(o.name.startswith("Real_hssd(") for o in tabs) and any(o.name.startswith("TableDiningFactory") for o in tabs):
            for o in [o for o in tabs if o.name.startswith("TableDiningFactory")]:
                bpy.data.objects.remove(o, do_unlink=True)
            tabs = [o for o in tabs if o.name.startswith("Real_hssd(")]
        tb = max(tabs, key=lambda o: (_bb(o)[1][0] - _bb(o)[0][0]) * (_bb(o)[1][1] - _bb(o)[0][1])); a, b = _bb(tb); cx, cy = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2; w, d = b[0] - a[0], b[1] - a[1]
        near = [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith(R2_CHAIRN) and _in_box(o, lo, hi) and 0.4 < _bb(o)[1][2] - z0 < 1.3
                and math.hypot((_bb(o)[0][0] + _bb(o)[1][0]) / 2 - cx, (_bb(o)[0][1] + _bb(o)[1][1]) / 2 - cy) < max(w, d) / 2 + 1.0]
        if st.get("r2_chairs") == "coherent":
            for o in near:
                bpy.data.objects.remove(o, do_unlink=True); removed += 1
            near = []
        need = 4 - len(near)
        if need <= 0:
            continue
        bpy.context.view_layer.update()
        tbr = (a[0] - 0.05, b[0] + 0.05, a[1] - 0.05, b[1] + 0.05); obs = [q for q in _obs_all(lo, hi) if not (q[0] <= cx <= q[1] and q[2] <= cy <= q[3])]
        for o in near:
            q = _bb(o); obs.append((q[0][0], q[1][0], q[0][1], q[1][1]))
        long_x = w >= d
        pts = []
        for s_ in (0.0, 0.4, -0.4):                                                           # the two long sides first, then the ends
            for sg in (-1, 1):
                pts.append((cx + (s_ if long_x else sg * (w / 2 + 0.32)), cy + (sg * (d / 2 + 0.32) if long_x else s_)))
        for sg in (-1, 1):
            pts.append((cx + (sg * (w / 2 + 0.32) if long_x else 0.0), cy + (0.0 if long_x else sg * (d / 2 + 0.32))))
        col = (0.95, 0.95, 0.93) if (u.get("dining") == "white_oval") else (0.92, 0.88, 0.8)
        for k, (x, y) in enumerate(pts):
            if need <= 0:
                break
            rc = (x - 0.27, x + 0.27, y - 0.27, y + 0.27)
            if not (lo[0] + 0.2 < x < hi[0] - 0.2 and lo[1] + 0.2 < y < hi[1] - 0.2) or any(rc[0] < q[1] and q[0] < rc[1] and rc[2] < q[3] and q[2] < rc[3] for q in obs):
                continue
            ch = ra.abo("deskchair", 700 + k, x, y, z0, math.atan2(cy - y, cx - x) + 0.0)
            if ch is not None:
                _recolour(ch, col, f"ir_apt_r2chair_{int(col[0] * 100)}", 0.6); _t(ch, "chair"); obs.append(rc); need -= 1; placed += 1
    stats["apt_r2_chairs"] = {"placed": placed, "removed": removed}


def _r2_extras(st, stats):
    """p7: a yellow footstool in unit B's living room; a floral sofa for the pink sitting room is set in _palette."""
    ra = _ra(); n = 0
    for r, (lo, hi, t) in _rooms().items():
        if t != "living-room" or not st.get("r2_footstool") or _unit(STY, (lo[0] + hi[0]) / 2) != "B":
            continue
        bpy.context.view_layer.update(); sp = _free_patch(lo, hi, _obs_all(lo, hi), 0.6, 0.6, margin=0.35)
        if sp is not None:
            o = ra.hssd(r"pouf|ottoman|footstool|foot stool", 710, sp[0], sp[1], lo[2], 0.0, fit=(0.55, 0.55, 0.42), size=(0.3, 1.0))
            if o is not None:
                _recolour(o, (0.95, 0.75, 0.05), "ir_apt_r2_footstool", 0.8); _t(o, "footstool"); n += 1
    stats["apt_r2_footstools"] = n


def apply(stats):
    global STY
    sc = bpy.context.scene
    if os.environ.get("ROOM_APT_SHELL") != "1" or sc.get("ir_apt_shell") or not any(o.name.endswith(".floor") for o in bpy.data.objects):
        return 0
    skip = set((os.environ.get("ROOM_APT_SKIP") or "").split(",")); n = 0
    STY = st = _style()                                               # the style table (units + per-unit finishes); parts read the unit ranges from it
    for key, fn in (("floor", _floor), ("walls", _walls), ("light", _lights), ("wardrobe", _wardrobes), ("bedding", _bedding), ("layers", _bedding_layers), ("rugs", _rugs), ("bedside", _bedside), ("bath", _baths), ("dining", _dining), ("feature", _feature), ("kitchen", _kitchen), ("palette", _palette), ("decor", _decor), ("p9work", _p9_work), ("curtains", _curtains), ("ratio2", _r2), ("doors", _doors_close)):
        if key in skip:
            continue
        if key == "doors" and not st.get("close_doors"):
            continue
        if key == "ratio2" and not st.get("ratio2"):
            continue
        try:
            bpy.context.view_layer.update(); fn(st, stats); n += 1
        except Exception as ex:                                       # noqa: BLE001 -- a part that fails must not sink the kit stage
            import traceback; traceback.print_exc()
            stats[f"apt_{key}_error"] = repr(ex)[:160]
    if os.environ.get("APT_REALISM") == "1":
        __import__("apt_realism").apply(stats)
    if os.environ.get("APT_CORRIDOR") == "1":
        __import__("apt_corridor").apply(stats)
    _aptb_apply(st, stats)
    _aptc_apply(st, stats)
    _aptd_apply(st, stats)
    try:
        _ra().report(stats, "apt")
    except Exception:                                                 # noqa: BLE001
        pass
    sc["ir_apt_shell"] = 1
    return n


# pkg_h_aptb: reference-directed apartment assemblies. Enabled one tested item at a time.
_APTB_ENABLED = ('p8_01', 'p8_02', 'p8_03', 'p8_04', 'p8_05', 'p8_06', 'p8_07', 'p8_08', 'p8_09', 'p8_10', 'p8_11', 'p8_12', 'p8_13', 'p8_14', 'p8_15', 'p7_01', 'p7_02', 'p7_03', 'p7_04', 'p7_05', 'p7_06', 'p7_07', 'p7_08', 'p7_09', 'p7_10', 'p7_11', 'p7_12', 'p7_13', 'p7_14', 'p7_15')


def _aptb_mat(name, rgb, rough=.5, metal=0, glass=0):
    """Clean physical shader: do not inherit linked tint/emission from a generic slot."""
    m = bpy.data.materials.get('aptb_'+name)
    if m is not None:
        return m
    m = bpy.data.materials.new('aptb_'+name); m.use_nodes = True
    b = m.node_tree.nodes.get('Principled BSDF')
    b.inputs['Base Color'].default_value = (*rgb,1)
    b.inputs['Roughness'].default_value = rough
    b.inputs['Metallic'].default_value = metal
    b.inputs['Transmission Weight'].default_value = glass
    b.inputs['IOR'].default_value = 1.45 if glass else 1.5
    return m


def _aptb_wood(name, rgb):
    m = _aptb_mat(name,rgb,.45)
    if m.get('aptb_wood'):return m
    n=m.node_tree.nodes;l=m.node_tree.links;b=n.get('Principled BSDF')
    tc=n.new('ShaderNodeTexCoord');mp=n.new('ShaderNodeVectorMath');mp.operation='MULTIPLY';mp.inputs[1].default_value=(3,75,3);l.new(tc.outputs['Generated'],mp.inputs[0])
    no=n.new('ShaderNodeTexNoise');no.inputs['Scale'].default_value=1;no.inputs['Detail'].default_value=3;l.new(mp.outputs[0],no.inputs['Vector'])
    ramp=n.new('ShaderNodeValToRGB');ramp.color_ramp.elements[0].color=(*(c*.7 for c in rgb),1);ramp.color_ramp.elements[1].color=(*(min(1,c*1.2) for c in rgb),1)
    l.new(no.outputs['Fac'],ramp.inputs[0]);l.new(ramp.outputs[0],b.inputs['Base Color'])
    bu=n.new('ShaderNodeBump');bu.inputs['Distance'].default_value=.0004;bu.inputs['Strength'].default_value=.2;l.new(no.outputs['Fac'],bu.inputs['Height']);l.new(bu.outputs[0],b.inputs['Normal']);m['aptb_wood']=1
    return m


def _aptb_box(name, loc, size, mat, bevel=.003):
    bpy.ops.mesh.primitive_cube_add(size=1,location=loc)
    o=bpy.context.object;o.name='aptb_'+name;o.dimensions=size
    bpy.ops.object.transform_apply(location=False,rotation=False,scale=True)
    o.data.materials.append(mat)
    if bevel:
        q=o.modifiers.new('Joinery edge radius','BEVEL');q.width=bevel;q.segments=3
        o.modifiers.new('Weighted normals','WEIGHTED_NORMAL')
    return o


def _aptb_asset(asset_id, name, pos, fit, yaw=0):
    """Pinned real mesh; reuse imported mesh or resolve the catalog, never a box fallback."""
    import abo_assets
    from mathutils import Matrix
    source=next((o for o in bpy.data.objects if o.type=='MESH' and asset_id in o.name),None)
    if source:
        o=bpy.data.objects.new('aptb_'+name,source.data.copy());bpy.context.scene.collection.objects.link(o)
    else:
        entry=next((e for e in abo_assets.entries() if e['id']==asset_id),None)
        if entry is None:
            import json
            for file in ('vendor_datasets/hssd_objects/hssd_object_index.json','vendor_datasets/polyhaven_models/polyhaven_object_index.json'):
                entry=next((e for e in json.load(open('/jarvis/project/robomituba/'+file))['objects'] if e['id']==asset_id),None)
                if entry:break
        if entry is None:raise RuntimeError('Missing pinned asset '+asset_id)
        o=abo_assets._import(entry,'aptb_'+name)
    o.matrix_world=Matrix.Identity(4)
    # Fit in local axes before rotating; fit is given in world-axis dimensions.
    raw=fit if abs(math.sin(yaw))<.5 else (fit[1],fit[0],fit[2])
    _ra()._stand(o,*pos,yaw,raw,grow=True);return o


def _aptb_room(r):
    import wall_face
    lo,hi,t=_rooms()[r];a,b=wall_face.inner_box(r)
    return lo,hi,a,b


def _aptb_remove(objects):
    for o in list(objects):
        if o.name in bpy.data.objects:bpy.data.objects.remove(o,do_unlink=True)


def _aptb_in(r,prefix):
    lo,hi,_=_rooms()[r]
    return [o for o in bpy.data.objects if o.type=='MESH' and o.name.startswith(prefix) and _in_box(o,lo,hi)]


def _aptb_upper(r,white=False):
    """Modeled glazed doors, carcass, interior shelves and visible crockery."""
    lo,hi,a,b=_aptb_room(r);x0=a[0]+.25;x1=b[0]-.30;y=b[1]-.19;z=lo[2]+1.55
    wood=_aptb_mat('white_shaker',(.82,.8,.74),.42) if white else _aptb_wood('walnut',(.16,.075,.032))
    gl=_aptb_mat('cabinet_glass',(.94,.96,.96),.025,glass=1);cream=_aptb_mat('ceramic',(.8,.77,.69),.22);brass=_aptb_mat('brass',(.5,.3,.08),.28,1)
    # Remove old opaque upper polygons, not appliances/base cabinetry.
    run=bpy.data.objects.get(f'apt_KitchenRun({r})')
    if run:
        import bmesh
        run.data=run.data.copy();bm=bmesh.new();bm.from_mesh(run.data);mw=run.matrix_world
        faces=[f for f in bm.faces if min((mw@v.co).z for v in f.verts)>lo[2]+1.35]
        bmesh.ops.delete(bm,geom=faces,context='FACES');bm.to_mesh(run.data);bm.free()
    for k in range(4):
        x=x0+(k+.5)*(x1-x0)/4;w=(x1-x0)/4-.01;h=.68
        for side,dx,dz,sx,sz in [('l',-w/2+.025,h/2,.05,h),('r',w/2-.025,h/2,.05,h),('t',0,h-.025,w,.05),('b',0,.025,w,.05)]:
            _aptb_box(f'{r}_upper{k}_{side}',(x+dx,y-.16,z+dz),(sx,.045,sz),wood)
        _aptb_box(f'{r}_upper{k}_glass',(x,y-.165,z+h/2),(w-.10,.008,h-.10),gl,.001)
        _aptb_box(f'{r}_upper{k}_back',(x,y+.15,z+h/2),(w,.025,h),wood)
        for j in range(3):
            _aptb_box(f'{r}_upper{k}_shelf{j}',(x,y,z+.02+j*.28),(w,.30,.02),wood)
            # Real dishes from the library; two per visible shelf.
            for q in range(2):
                o=_aptb_asset('HSSD_21551881391c2b21c2e1358effa7d6b69cbd435f' if q==0 else 'HSSD_0128475579600f804ec7ef1cf8a212622760cfd1',f'{r}_dish{k}_{j}_{q}',(x+(q-.5)*w*.4,y-.03,z+.032+j*.28),(.16,.16,.17))
                if o is None:raise RuntimeError('Crockery asset unavailable')
                o.name=f'aptb_{r}_dish{k}_{j}_{q}'
        _aptb_box(f'{r}_upper{k}_pull',(x+w*.34,y-.20,z+.32),(.02,.03,.12),brass,.008)
    return 4


def _aptb_island(r,white):
    lo,hi,a,b=_aptb_room(r);old=_aptb_in(r,('CafeCounterFactory',))
    if not old:raise RuntimeError('Expected cafe island in '+r)
    aa,bb=_bb(old[0]);cx,cy=(aa[0]+bb[0])/2,(aa[1]+bb[1])/2;w=min(2.6,bb[0]-aa[0]);d=.82;z=lo[2]
    wood=_aptb_mat('white_shaker',(.82,.8,.74),.42) if white else _aptb_wood('walnut',(.16,.075,.032))
    stone=_aptb_mat('pale_stone' if white else 'dark_stone',(.75,.72,.66) if white else (.035,.038,.04),.28)
    # Actual hollow cabinet shell, four recessed fronts, handles, top and feet.
    for dx in [-w/2+.02,w/2-.02]:_aptb_box(r+'_island_side',(cx+dx,cy,z+.45),(.04,d,.81),wood)
    _aptb_box(r+'_island_base',(cx,cy,z+.12),(w,d,.04),wood)
    _aptb_box(r+'_island_top',(cx,cy,z+.9),(w+.06,d+.06,.045),stone,.012)
    for k in range(4):
        x=cx-w/2+(k+.5)*w/4
        _aptb_box(r+f'_island_door{k}',(x,cy-d/2,z+.5),(w/4-.015,.035,.72),wood)
        _aptb_box(r+f'_island_handle{k}',(x,cy-d/2-.025,z+.73),(.13,.02,.018),_aptb_mat('brass',(.5,.3,.08),.28,1),.006)
    _aptb_remove(old);return 1


def _aptb_dining(r,white=False,six=False):
    lo,hi,a,b=_aptb_room(r);z=lo[2]
    old=_aptb_in(r,('TableDiningFactory','Real_deskchair','ChairFactory','apt_R2Chair','apt_Table'))
    # Include the shell's auxiliary HSSD dining table but not fridge/counter props.
    for o in _aptb_in(r,('Real_hssd(',)):
        aa,bb=_bb(o)
        if .60<bb[2]-z<.85 and min(bb[i]-aa[i] for i in [0,1])>.65:old.append(o)
    cx,cy=(a[0]+b[0])/2, a[1]+1.65
    table=_aptb_asset('HSSD_fdc07a59b1ffb24d6de5646547d6fe08da8ae5a4',r+'_dining',(cx,cy,z),(2.0,1.0,.76)) if white else _aptb_asset('HSSD_406dc5c9cf5499f0e865f41a7a18f8a2acc1a5b4',r+'_dining',(cx,cy,z),(1.30,1.30,.75))
    if white:_set_slots(table,_aptb_mat('white_shaker',(.82,.8,.74),.42))
    # Use a controlled footprint, retaining real joinery mesh.
    bpy.context.view_layer.update();ta,tb=_bb(table);w,d=tb[0]-ta[0],tb[1]-ta[1]
    count=6 if six else 4
    points=[(cx+sg*.55,cy+side*.88) for sg in [-1,1] for side in [-1,1]] if six else [(cx-.92,cy),(cx+.92,cy),(cx,cy-.92),(cx,cy+.92)]
    if six:points += [(cx-1.3,cy),(cx+1.3,cy)]
    for k,(x,y) in enumerate(points):
        c=_aptb_asset('B085552QQB',r+f'_chair{k}',(x,y,z),(.54,.56,.82),math.atan2(cy-y,cx-x)+math.pi/2)
        _recolour(c,(.82,.79,.71) if white else (.72,.67,.56),'aptb_dining_fabric',.85)
    _aptb_remove(set(old));return count


def _aptb_green(pos,name,h=.35):
    o=_ra().hssd('pothos|croton|ficus|money tree',71,*pos,0,fit=(h*.7,h*.7,h),cats=('plant','planter','flowerpot'),size=(.15,3),grow=True)
    if o is None:raise RuntimeError('No leafy plant for '+name)
    o.name='aptb_'+name;_aptb_fix_leaf([o]);return o


def _aptb_fix_leaf(objects):
    count=0
    for o in objects:
        if o.type!='MESH':continue
        o.data=o.data.copy()
        for slot in o.material_slots:
            if not slot.material or not slot.material.use_nodes:continue
            slot.material=slot.material.copy();nt=slot.material.node_tree
            for bs in nt.nodes:
                if bs.type!='BSDF_PRINCIPLED':continue
                for key,val in [('IOR',1.45),('Specular IOR Level',.3),('Metallic',0),('Transmission Weight',0),('Emission Strength',0),('Roughness',.65)]:
                    for link in list(bs.inputs[key].links):nt.links.remove(link)
                    bs.inputs[key].default_value=val
        count+=1
    return count


def _aptb_counter_dress(r):
    lo,hi,a,b=_aptb_room(r);run=bpy.data.objects.get(f'apt_KitchenRun({r})')
    if run is None:raise RuntimeError('Kitchen run absent')
    x=a[0]+.6;y=b[1]-.34;z=lo[2]+.94
    _aptb_green((x,y,z),r+'_counter_green',.28)
    _aptb_asset('HSSD_695e49c5fe19b4a0e70078f755a2dece95533d86',r+'_utensil_box',(x+.45,y,z),(.16,.15,.17))
    o=_aptb_asset('HSSD_c139234bf8464898e67b064e1726440a3e84b0b6',r+'_board',(x+.8,y,z),(.28,.15,.3))
    if o is None:raise RuntimeError('No cutting board asset')
    o.name='aptb_'+r+'_board'
    for k in range(3):
        o=_aptb_asset('HSSD_3b63f000011404011c4aeb3f19bb04a112535634',r+f'_utensil{k}',(x+.4+k*.035,y,z+.1),(.035,.035,.22))
        if o is None:raise RuntimeError('No kitchen utensil asset')
        o.name='aptb_'+r+f'_utensil{k}'
    return 6


def _aptb_living_sofa(r,col,pos,fit,yaw=0):
    lo,hi,a,b=_aptb_room(r)
    old=_aptb_in(r,('AboSofaFactory','LoveseatFactory','Real_loungesofa'))
    o=_aptb_asset('B07B4MF2MF',r+'_sofa',pos,fit,yaw)
    _recolour(o,col,'aptb_'+r+'_sofa',.85);_aptb_remove(old);return o


def _aptb_smoke_globes(r,anchor):
    lo,hi,a,b=_aptb_room(r);glass=_aptb_mat('smoked_glass',(.12,.10,.08),.08,glass=.9)
    for k,(dx,dy,z) in enumerate([(-.25,-.1,2.03),(.18,.14,1.88),(.35,-.2,2.10)]):
        x,y=anchor[0]+dx,anchor[1]+dy
        _globe('aptb_'+r+f'_smoked{k}',x,y,z,glass,r=.12)
        _globe('aptb_'+r+f'_bulb{k}',x,y,z,_emit('aptb_bulb',(1,.77,.48),2),r=.018)
        _light('aptb_'+r+f'_bulbLight{k}','POINT',(x,y,z),3,(1,.8,.58),r=.02)
        _aptb_box(r+f'_cable{k}',(x,y,(z+b[2]+2.3)/2),(.005,.005,max(.03,lo[2]+2.3-z)),_aptb_mat('black',(.02,.02,.02)))
    return 3


def _aptb_sideboard(r,pos,white=False):
    old=_aptb_in(r,('AboDresserFactory',))
    o=_ra().hssd('sideboard|credenza',12,*pos,0,fit=(1.8,.45,.8),size=(1,2.5),grow=True)
    if o is None:raise RuntimeError('Real sideboard asset absent')
    o.name='aptb_'+r+'_sideboard';bpy.context.view_layer.update();a,b=_bb(o)
    _recolour(o,(.82,.8,.74) if white else (.18,.09,.04),'aptb_sideboard_white' if white else 'aptb_sideboard_walnut',.4)
    lp=_ra().abo('tablelamp',22,pos[0]+.45,pos[1],b[2],0,fit=(.28,.28,.45))
    if lp is None:raise RuntimeError('Real tablelamp absent')
    lp.name='aptb_'+r+'_sideboard_lamp';_aptb_green((pos[0]-.45,pos[1],b[2]),r+'_sideboard_green',.28)
    _aptb_remove(old);return 1


def _aptb_art(r):
    lo,hi,a,b=_aptb_room(r);old=_aptb_in(r,('Real_hssd(HSSD_02ca947','Real_hssd(HSSD_0e527'))
    cream=_aptb_mat('art_cream',(.73,.7,.63),.85);dark=_aptb_mat('art_charcoal',(.035,.033,.03),.85);tan=_aptb_mat('art_tan',(.4,.34,.25),.85)
    x=(a[0]+b[0])/2;y=b[1]-.025;z=lo[2]+1.7
    _aptb_box(r+'_abstract_frame',(x,y,z),(1.3,.03,.85),_aptb_mat('black',(.02,.02,.02)),.005)
    _aptb_box(r+'_abstract_canvas',(x,y-.02,z),(1.24,.006,.79),cream,.001)
    _aptb_box(r+'_abstract_left',(x-.36,y-.025,z),(.38,.002,.73),dark,.001)
    _aptb_box(r+'_abstract_right',(x+.26,y-.027,z+.15),(.45,.002,.32),tan,.001)
    _aptb_remove(old);return 1


def _aptb_pattern(name, floral=False):
    import numpy as np
    m=_aptb_mat(name,(.8,.78,.72),.82)
    if m.get('aptb_pattern'):return m
    n=512;yy,xx=np.mgrid[0:n,0:n].astype(float)/n;imarr=np.ones((n,n,4),dtype=np.float32)
    imarr[:,:,:3]=(.78,.75,.68) if not floral else (.17,.035,.025)
    rng=random.Random(812)
    for k in range(14 if floral else 9):
        cx,cy=rng.random(),rng.random();dx=(xx-cx+.5)%1-.5;dy=(yy-cy+.5)%1-.5
        rr=np.sqrt(dx*dx+dy*dy);ang=np.arctan2(dy,dx);edge=.035+.016*np.cos(5*ang)
        mask=rr<edge
        col=rng.choice([(.65,.15,.12),(.78,.34,.25),(.8,.52,.38),(.55,.10,.17)]) if floral else (.065,.15,.31)
        imarr[mask,:3]=col
        for q in [-1,1]:
            lx=(dx+q*.055)*.85+dy*.5;ly=-dx*.5+(dy+.035)*.85
            leaf=(lx/.035)**2+(ly/.012)**2<1
            imarr[leaf,:3]=(.08,.17,.065) if floral else (.10,.21,.36)
    im=bpy.data.images.new('aptb_'+name,width=n,height=n);im.colorspace_settings.name='Non-Color';im.pixels.foreach_set(imarr.ravel());im.pack()
    nt=m.node_tree;N=nt.nodes;L=nt.links;b=N.get('Principled BSDF');tex=N.new('ShaderNodeTexImage');tex.image=im;tex.extension='REPEAT'
    geo=N.new('ShaderNodeNewGeometry');sep=N.new('ShaderNodeSeparateXYZ');L.new(geo.outputs['Position'],sep.inputs[0]);add=N.new('ShaderNodeMath');add.operation='ADD';L.new(sep.outputs['X'],add.inputs[0]);L.new(sep.outputs['Y'],add.inputs[1]);vec=N.new('ShaderNodeCombineXYZ');L.new(add.outputs[0],vec.inputs['X']);L.new(sep.outputs['Z'],vec.inputs['Y']);scale=N.new('ShaderNodeVectorMath');scale.operation='SCALE';scale.inputs['Scale'].default_value=2.5 if floral else 3.0;L.new(vec.outputs[0],scale.inputs[0]);L.new(scale.outputs[0],tex.inputs[0]);L.new(tex.outputs[0],b.inputs['Base Color']);m['aptb_pattern']=1;return m


def _aptb_feature(key,st,stats):
    """Exactly one reference target per batch. Caller records enabled keys."""
    p8=key.startswith('p8_');rB='kitchen_0/1';rA='kitchen_0/0';liv='living-room_0/0'
    if key=='p8_01':return _aptb_upper(rB,True)
    if key=='p8_02':return _aptb_island(rB,True)
    if key=='p8_03':
        n=_aptb_dining(rB,True,True);lo,hi,a,b=_aptb_room(rB)
        _aptb_box('B_dining_rug',((a[0]+b[0])/2,a[1]+1.65,lo[2]+.008),(3.25,2.45,.012),_aptb_mat('navy_rug',(.04,.065,.12),.95),.007);return n
    if key=='p8_04':
        lo,hi,a,b=_aptb_room(rB);table=bpy.data.objects.get('aptb_'+rB+'_dining')
        if table is None:raise RuntimeError('Festive spread requires new dining table')
        aa,bb=_bb(table);cx,cy=(aa[0]+bb[0])/2,(aa[1]+bb[1])/2;z=bb[2]+.003
        for k in range(6):
            x=cx+[-.55,.55,-.55,.55,-.75,.75][k];y=cy+[-.30,-.30,.30,.30,0,0][k]
            _aptb_asset('HSSD_21551881391c2b21c2e1358effa7d6b69cbd435f',f'festive_plate{k}',(x,y,z),(.24,.24,.025))
            _aptb_asset('HSSD_036edf04844210dae3f5afc59165ad4955b3510b',f'festive_glass{k}',(x+.12,y,z),(.08,.08,.18))
        _aptb_green((cx,cy,z),'festive_runner',.22)
        _aptb_asset('HSSD_87ac831ae9463acf6ee6a876de63ed07561aef03','kitchen_tree',(b[0]-.48,a[1]+.6,lo[2]),(.75,.75,1.8))
        wreath=_aptb_asset('HSSD_27954882e94f505fec9cc13382bb6348801762f2','kitchen_wreath',(b[0]-.5,b[1]-.4,lo[2]+1.7),(.45,.10,.45));return 15
    if key=='p8_05':
        st['B']['wall']='toile'
        # Remove previous panel meshes before rebuilding: coplanar duplicates render black.
        _aptb_remove([o for o in bpy.data.objects if o.name.startswith('apt_Wainscot(')])
        _walls(st,stats)
        for o in bpy.data.objects:
            if o.name.startswith('apt_Wainscot('):_set_slots(o,_aptb_mat('white_panel_paint',(.82,.8,.75),.5))
        mat=_aptb_pattern('dense_blue_toile')
        count=0
        for r,(lo,hi,t) in _rooms().items():
            if (lo[0]+hi[0])/2<12 or t not in ('bedroom','living-room','kitchen','hallway'):continue
            w=bpy.data.objects.get(r+'.wall')
            if w:_set_slots(w,mat);count+=1
        return count
    if key=='p8_06':
        run=bpy.data.objects.get('apt_KitchenRun(kitchen_0/0)')
        if run is None:raise RuntimeError('A kitchen run missing')
        wood=_aptb_wood('walnut',(.16,.075,.032))
        for slot in run.material_slots:
            if slot.material and slot.material.name.startswith(('ir_apt_kfront','ir_apt_kpanel')):slot.material=wood
        n=_aptb_upper(rA,False)
        lo,hi,a,b=_aptb_room(rA)
        # A small detailed return, below upper cabinets and clear of west doorway.
        for name,loc,size in [('side',(a[0]+.03,b[1]-.7,lo[2]+.45),(.035,.9,.86)),('top',(a[0]+.33,b[1]-.7,lo[2]+.91),(.65,.95,.04)),('door',(a[0]+.62,b[1]-.7,lo[2]+.47),(.035,.85,.75))]:_aptb_box('A_return_'+name,loc,size,wood)
        return n
    if key=='p8_07':
        lo,hi,a,b=_aptb_room(rA);z=lo[2]+.94;y=b[1]-.35;x=a[0]+.7
        _aptb_asset('HSSD_ceb4c6ac0c61b788a902704c3bc77112307dec63','coffee_maker',(x,y,z),(.25,.3,.36))
        _aptb_asset('HSSD_689686140b7ab8fd656ce588f10f8c40568da3bf','kettle',(x+.4,y,z),(.22,.22,.3))
        # Clock lies in its real imported plane; place with existing wall-picture helper.
        clock=_ra().hssd('HSSD_20c32bc8e148545c59afd79fdfe8ea3155073179',0,b[0]-.5,b[1]-.09,lo[2]+1.4,math.pi,fit=(.32,.05,.32),grow=True)
        if clock is None:raise RuntimeError('Clock unavailable')
        clock.name='aptb_kitchen_clock'
        _aptb_box('coffee_glassware_shelf',(a[0]+1.5,b[1]-.18,lo[2]+1.45),(1.0,.28,.025),_aptb_wood('walnut',(.16,.075,.032)))
        for k in range(4):_aptb_asset('HSSD_036edf04844210dae3f5afc59165ad4955b3510b',f'shelf_glass{k}',(a[0]+1.15+.22*k,b[1]-.18,lo[2]+1.47),(.08,.08,.17))
        return 8
    if key=='p8_08':return _aptb_counter_dress(rA)+_aptb_counter_dress(rB)
    if key=='p8_09':
        n=_aptb_dining(rA,False,False);o=bpy.data.objects.get('aptb_'+rA+'_dining');aa,bb=_bb(o);_aptb_green(((aa[0]+bb[0])/2,(aa[1]+bb[1])/2,bb[2]),'A_dining_centerpiece',.3);return n+1
    if key=='p8_10':
        n=_aptb_island(rA,False);old=_aptb_in(rA,('apt_GlobeShell','apt_Globe('));_aptb_remove(old);return n+_aptb_smoke_globes(rA,(8.81,8.60))
    if key=='p8_11':
        _aptb_living_sofa(liv,(.16,.18,.20),(2.75,4.63,.144),(2.3,.90,.9),math.pi);return 1
    if key=='p8_12':return _aptb_smoke_globes(liv,(2.82,6))
    if key=='p8_13':return _aptb_sideboard(liv,(4.12,7.615,.144))
    if key=='p8_14':return _aptb_art(liv)
    if key=='p8_15':
        objs=[o for o in bpy.data.objects if o.type=='MESH' and ('HSSD_09ca84e' in o.name or 'plant' in str(o.get('apt_role','')).lower())]
        n=_aptb_fix_leaf(objs)
        for r,lo,hi,cx,cy,ax,hd,L,W,zt in _beds():
            for sign in [-1,1]:
                # At real bedside support height; close to lamp rather than floating.
                lamps=_aptb_in(r,('apt_BedLamp',))
                if lamps:
                    aa,bb=_bb(lamps[0 if sign<0 else -1]);_aptb_green(((aa[0]+bb[0])/2+sign*.13,(aa[1]+bb[1])/2,aa[2]),r+f'_bed_green{sign}',.18);n+=1
        return n
    if key=='p7_01':
        r='kitchen_0/2';n=_aptb_upper(r,False);lo,hi,a,b=_aptb_room(r)
        # Real glazed cupboards plus a low sideboard, clear of the north work run.
        o=_ra().hssd('sideboard|credenza',12,b[0]-.26,a[1]+1.4,lo[2],math.pi/2,fit=(1.25,.42,.8),size=(1,2.5),grow=True)
        if o is None:raise RuntimeError('C display sideboard unavailable')
        o.name='aptb_C_kitchen_sideboard';_recolour(o,(.24,.12,.055),'aptb_C_sideboard',.5);return n+1
    if key=='p7_02':
        r='kitchen_0/0';n=_aptb_dining(r,False,True);old=bpy.data.objects.get('aptb_'+r+'_dining');aa,bb=_bb(old);cx,cy=(aa[0]+bb[0])/2,(aa[1]+bb[1])/2;lo,hi,a,b=_aptb_room(r)
        table=_aptb_asset('B07SJ75Y1M','A_timber_dining',(cx,cy,lo[2]),(1.8,.9,.76))
        bpy.context.view_layer.update();aa,bb=_bb(table);table.scale.x*=1.8/(bb[0]-aa[0]);bpy.context.view_layer.update();aa,bb=_bb(table);table.location.x+=cx-(aa[0]+bb[0])/2
        bpy.data.objects.remove(old,do_unlink=True)
        for o in bpy.data.objects:
            if o.name.startswith('aptb_'+r+'_chair'):_set_big_slot(o,_aptb_mat('rust_chair',(.42,.15,.075),.85))
        _aptb_box('A_dining_rug',(cx,cy,lo[2]+.008),(3.3,2.6,.012),_aptb_mat('A_dining_rug',(.46,.39,.29),.95),.007);return n+1
    if key=='p7_03':
        n=0
        for r,(lo,hi,t) in _rooms().items():
            if t!='kitchen':continue
            n+=_aptb_counter_dress(r)
            tables=_aptb_in(r,('aptb_A_timber_dining','TableDiningFactory','apt_Table','aptb_'+r+'_dining'))
            if not tables:raise RuntimeError('Missing dining support '+r)
            aa,bb=_bb(tables[0]);_aptb_green(((aa[0]+bb[0])/2,(aa[1]+bb[1])/2,bb[2]+.002),r+'_table_green',.28);n+=1
        return n
    if key=='p7_04':
        o=bpy.data.objects.get('kitchen_0/1.floor')
        if o is None:raise RuntimeError('Kitchen B floor missing')
        _set_slots(o,_aptb_yellow_boards());return 1
    if key=='p7_05':return _aptb_basin('bathroom_0/2')
    if key=='p7_06':return _aptb_bath_tiles()
    if key=='p7_07':return _aptb_blocks()
    if key=='p7_08':
        objs=[o for o in bpy.data.objects if o.type=='MESH' and 'HSSD_09ca84e' in o.name];n=_aptb_fix_leaf(objs)
        for r,lo,hi,cx,cy,ax,hd,L,W,zt in _beds():
            lamps=_aptb_in(r,('apt_BedLamp',))
            if lamps:
                aa,bb=_bb(lamps[0]);_aptb_green(((aa[0]+bb[0])/2+.13,(aa[1]+bb[1])/2,aa[2]),r+'_bedside_green',.18);n+=1
        return n
    if key=='p7_09':
        sofas=_aptb_in('living-room_0/1',('AboSofaFactory','LoveseatFactory','Real_loungesofa'))
        if not sofas:raise RuntimeError('B sofa missing')
        mat=_aptb_mat('B_striped_sofa',(.7,.67,.58),.85);nt=mat.node_tree;tc=nt.nodes.new('ShaderNodeTexCoord');wave=nt.nodes.new('ShaderNodeTexWave');wave.wave_type='BANDS';wave.bands_direction='X';wave.inputs['Scale'].default_value=7
        nt.links.new(tc.outputs['Generated'],wave.inputs['Vector']);ramp=nt.nodes.new('ShaderNodeValToRGB');ramp.color_ramp.interpolation='CONSTANT';ramp.color_ramp.elements[0].position=.48;ramp.color_ramp.elements[0].color=(.025,.025,.022,1);ramp.color_ramp.elements[1].position=.5;ramp.color_ramp.elements[1].color=(.78,.75,.65,1)
        nt.links.new(wave.outputs['Fac'],ramp.inputs[0]);nt.links.new(ramp.outputs[0],nt.nodes.get('Principled BSDF').inputs['Base Color'])
        for o in sofas:_set_big_slot(o,mat)
        return len(sofas)
    if key=='p7_10':
        sofas=_aptb_in('living-room_0/3',('AboSofaFactory','LoveseatFactory','Real_loungesofa'))
        if not sofas:raise RuntimeError('Floral sofa missing')
        for o in sofas:_set_big_slot(o,_aptb_pattern('dense_color_floral',True))
        return len(sofas)
    if key=='p7_11':return _aptb_paper()
    if key=='p7_12':return _aptb_open_curtains()
    if key=='p7_13':return _aptb_missing_bed(st,stats)
    if key=='p7_14':
        r='living-room_0/0';lo,hi,a,b=_aptb_room(r)
        # Clear the prior armchair and bookcase envelope, retaining both in usable positions.
        for o in _aptb_in(r,('AboArmchairFactory','ArmChairFactory','Real_loungechair','AboBookcaseFactory')):
            aa,bb=_bb(o)
            if bb[1]<8:continue
            x,y=(.8,6.1) if 'Bookcase' not in o.name else (3.95,5.1)
            yaw=0 if 'Bookcase' not in o.name else -math.pi/2
            _ra()._stand(o,x,y,lo[2],yaw,(.8,.85,.9) if 'Bookcase' not in o.name else (.9,.4,1.65),grow=True)
        sofa=_aptb_asset('B07K8V2JRF','A_red_chaise',(2.2,8.92,lo[2]),(2.65,1.65,.88))
        _set_big_slot(sofa,_aptb_mat('burgundy_weave',(.3,.025,.035),.85));return 1
    if key=='p7_15':
        r='living-room_0/2';lo,hi,a,b=_aptb_room(r)
        _aptb_living_sofa(r,(.055,.06,.065),(22.35,6.28,lo[2]),(1.8,.83,.85))
        _aptb_remove(_aptb_in(r,('AboBookcaseFactory','AboCoffeeFactory','TableCoffeeFactory')))
        table=_ra().abo('roundtable',91,22.35,5.25,lo[2],0,fit=(.62,.62,.4))
        if table is None:raise RuntimeError('C round coffee table unavailable')
        table.name='aptb_C_round_coffee';_set_big_slot(table,_aptb_mat('black_glass',(.025,.025,.025),.12,glass=.25))
        # Detailed low open console against west wall, replacing the tall conflicting bookcase.
        black=_aptb_mat('black_console',(.022,.022,.022),.45)
        for z in [.15,.53]:_aptb_box('C_console_shelf',(20.4,5.4,lo[2]+z),(.35,1.1,.025),black)
        for y in [4.86,5.94]:_aptb_box('C_console_side',(20.4,y,lo[2]+.34),(.35,.025,.4),black)
        _aptb_green((20.4,5.65,lo[2]+.545),'C_console_green',.24);return 3
    raise KeyError(key)


def _aptb_apply(st,stats):
    style=next((name for name,value in STYLES.items() if value is st),None)
    completed=set(str(bpy.context.scene.get('pkg_h_aptb_done','')).split(','))
    for key in _APTB_ENABLED:
        if not key.startswith(style+'_') or key in completed:continue
        n=_aptb_feature(key,st,stats)
        if not n:raise RuntimeError('Empty apartment reference repair '+key)
        completed.add(key);bpy.context.scene['pkg_h_aptb_done']=','.join(sorted(completed));stats['pkg_h_aptb_'+key]=n

def _aptb_paper():
    count=0
    paper=_aptb_mat('paper_shell',(.76,.72,.63),.8)
    nt=paper.node_tree;n=nt.nodes;l=nt.links
    if not paper.get('thin_paper'):
        bs=n.get('Principled BSDF');tr=n.new('ShaderNodeBsdfTranslucent');tr.inputs[0].default_value=(.85,.8,.68,1);mix=n.new('ShaderNodeMixShader');mix.inputs[0].default_value=.55;l.new(bs.outputs[0],mix.inputs[1]);l.new(tr.outputs[0],mix.inputs[2]);out=n.get('Material Output');l.new(mix.outputs[0],out.inputs['Surface']);paper['thin_paper']=1
    rib=_aptb_mat('paper_rib',(.48,.43,.33),.8)
    for o in list(bpy.data.objects):
        if not o.name.startswith('apt_R2Globe('):continue
        a,b=_bb(o);cx,cy,cz=[(a[k]+b[k])/2 for k in range(3)];radius=(b[0]-a[0])/2
        _set_slots(o,paper)
        for j in range(-7,8):
            z=cz+j*radius/8;rad=math.sqrt(max(0,radius**2-(z-cz)**2))
            bpy.ops.mesh.primitive_torus_add(major_segments=48,minor_segments=6,location=(cx,cy,z),major_radius=rad,minor_radius=.0018)
            q=bpy.context.object;q.name='aptb_paper_rib_'+o.name+str(j);q.data.materials.append(rib)
        count+=1
    return count


def _aptb_open_curtains():
    from mathutils import Matrix
    count=0
    for o in list(bpy.data.objects):
        if not o.name.startswith('apt_Sheer('):continue
        a,b=_bb(o);axis=0 if b[0]-a[0]>b[1]-a[1] else 1;span=b[axis]-a[axis]
        for side in [0,1]:
            q=bpy.data.objects.new('aptb_open_'+o.name+str(side),o.data.copy());bpy.context.scene.collection.objects.link(q);q.matrix_world=o.matrix_world.copy();inv=q.matrix_world.inverted()
            for v in q.data.vertices:
                p=q.matrix_world@v.co;t=(p[axis]-a[axis])/span
                p[axis]=a[axis]+t*span*.14 if not side else b[axis]-span*.14+t*span*.14
                v.co=inv@p
        bpy.data.objects.remove(o,do_unlink=True);count+=1
    return count


def _aptb_blocks():
    glass=_aptb_mat('wavy_privacy_glass',(.8,.87,.88),.22,glass=.9);mortar=_aptb_mat('glass_mortar',(.72,.72,.66),.8)
    if not glass.get('wavy'):
        nt=glass.node_tree;n=nt.nodes;l=nt.links;tex=n.new('ShaderNodeTexNoise');tex.inputs['Scale'].default_value=95;bu=n.new('ShaderNodeBump');bu.inputs['Strength'].default_value=.25;bu.inputs['Distance'].default_value=.003;l.new(tex.outputs['Fac'],bu.inputs['Height']);l.new(bu.outputs[0],n.get('Principled BSDF').inputs['Normal']);glass['wavy']=1
    old=[o for o in bpy.data.objects if o.name.startswith('apt_R2GlassBlock(')]
    count=0
    for o in old:
        a,b=_bb(o);cx,cy=(a[0]+b[0])/2,(a[1]+b[1])/2;alongx=b[0]-a[0]>b[1]-a[1];L=max(b[0]-a[0],b[1]-a[1]);H=b[2]-a[2]
        cols=max(1,int(L/.19));rows=max(1,int(H/.19))
        for i in range(cols):
            for j in range(rows):
                x=cx-L/2+(i+.5)*L/cols if alongx else cx;y=cy if alongx else cy-L/2+(i+.5)*L/cols
                size=(L/cols-.009,.075,H/rows-.009) if alongx else (.075,L/cols-.009,H/rows-.009)
                _aptb_box(f'glassblock_{count}_{i}_{j}',(x,y,a[2]+(j+.5)*H/rows),size,glass,.007)
        # Thin discrete mortar rails leave glass faces exposed, not a backing slab.
        for j in range(rows+1):
            _aptb_box(f'glassjoint_{count}_{j}',(cx,cy,a[2]+j*H/rows),(L,.07,.008) if alongx else (.07,L,.008),mortar,.002)
        for i in range(cols+1):
            x=cx-L/2+i*L/cols if alongx else cx;y=cy if alongx else cy-L/2+i*L/cols
            _aptb_box(f'glassjointV_{count}_{i}',(x,y,(a[2]+b[2])/2),(.008,.07,H) if alongx else (.07,.008,H),mortar,.002)
        bpy.data.objects.remove(o,do_unlink=True);count+=1
    return count


def _aptb_basin(r):
    import bmesh
    from room_planner import proc_boutique_flagship as fl
    old=_aptb_in(r,('apt_Vanity','apt_VanityGap'))
    lo,hi,a,b=_aptb_room(r);cx=(a[0]+b[0])/2;cy=a[1]+.28;bottom=lo[2]+.27;top=lo[2]+.84
    oak=_aptb_wood('vanity_oak',(.42,.28,.15));cer=_aptb_mat('ceramic',(.8,.77,.69),.22);metal=_aptb_mat('chrome',(.65,.67,.7),.18,1)
    for dx in [-.51,.51]:_aptb_box(r+'_vanity_side',(cx+dx,cy,(bottom+top)/2),(.035,.48,top-bottom),oak)
    for k in range(2):_aptb_box(r+f'_vanity_drawer{k}',(cx,cy+.245,bottom+.14+k*.25),(.99,.035,.23),oak)
    _aptb_box(r+'_vanity_bottom',(cx,cy,bottom),(1.05,.48,.03),oak)
    for dx,dy,sx,sy in [(-.4,0,.26,.5),(.4,0,.26,.5),(0,-.21,.55,.08),(0,.21,.55,.08)]:_aptb_box(r+'_basin_rim',(cx+dx,cy+dy,top), (sx,sy,.028),cer)
    bm=bmesh.new();rings=[]
    for z,sx,sy in [(top,.28,.17),(top-.06,.25,.145),(top-.13,.13,.08),(top-.15,.018,.018)]:
        ring=[bm.verts.new((cx+sx*math.cos(i*math.tau/48),cy+sy*math.sin(i*math.tau/48),z)) for i in range(48)];rings.append(ring)
    for j in range(3):
        for i in range(48):bm.faces.new((rings[j][i],rings[j][(i+1)%48],rings[j+1][(i+1)%48],rings[j+1][i]))
    mesh=bpy.data.meshes.new('OpenCeramicBasin');bm.to_mesh(mesh);bm.free();o=bpy.data.objects.new('aptb_'+r+'_open_basin',mesh);bpy.context.scene.collection.objects.link(o);mesh.materials.append(cer)
    for f in mesh.polygons:f.use_smooth=True
    # Actual mixer spout with separate neck and lever; no slab across bowl opening.
    fl.mesh_object('aptb_'+r+'_mixer',[(metal,[('cyl',(cx,cy-.19,top),(cx,cy-.19,top+.22),.018,24),('cyl',(cx,cy-.19,top+.22),(cx,cy-.02,top+.22),.015,24),('cyl',(cx,cy-.02,top+.22),(cx,cy-.02,top+.17),.015,24)])],bevel=True)
    _aptb_box(r+'_mixer_lever',(cx+.055,cy-.19,top+.12),(.07,.018,.018),metal,.007)
    _aptb_remove(old);return 1


def _aptb_bath_tiles():
    import bmesh
    count=0
    for r,(lo,hi,t) in _rooms().items():
        if t!='bathroom':continue
        w=bpy.data.objects.get(r+'.wall')
        if not w:continue
        plain=_aptb_mat('bath_plaster',(.78,.75,.68),.8)
        tile=_tile('aptb_terra_tile',(.28,.075,.035),.12,(.12,.07,.045),.2,brick=True) if r.endswith('/0') else _tile('aptb_cream_tile',(.78,.77,.71),.20,(.52,.50,.45),.3)
        # Project wall tiles in world horizontal distance and height, not XY floor coordinates.
        if not tile.get('aptb_wall_projection'):
            nt=tile.node_tree;n=nt.nodes;l=nt.links;geo=n.new('ShaderNodeNewGeometry');sep=n.new('ShaderNodeSeparateXYZ');l.new(geo.outputs['Position'],sep.inputs[0]);add=n.new('ShaderNodeMath');add.operation='ADD';l.new(sep.outputs['X'],add.inputs[0]);l.new(sep.outputs['Y'],add.inputs[1]);vec=n.new('ShaderNodeCombineXYZ');l.new(add.outputs[0],vec.inputs['X']);l.new(sep.outputs['Z'],vec.inputs['Y'])
            for node in n:
                if node.type=='TEX_BRICK':l.new(vec.outputs[0],node.inputs['Vector'])
            tile['aptb_wall_projection']=1
        w.data=w.data.copy();w.data.materials.clear();w.data.materials.append(plain);w.data.materials.append(tile)
        if r.endswith('/0'):
            bm=bmesh.new();bm.from_mesh(w.data);mw=w.matrix_world;inv=mw.inverted();plane=hi[0]-1.12
            bmesh.ops.bisect_plane(bm,geom=list(bm.verts)+list(bm.edges)+list(bm.faces),dist=.0001,plane_co=inv@Vector((plane,lo[1],lo[2])),plane_no=(mw.to_3x3().transposed()@Vector((1,0,0))).normalized())
            for f in bm.faces:f.material_index=1 if (mw@f.calc_center_median()).x>=plane-.001 else 0
            bm.to_mesh(w.data);bm.free()
        else:
            for f in w.data.polygons:f.material_index=1
        count+=1
    return count


def _aptb_missing_bed(st,stats):
    r='bedroom_0/4';lo,hi,a,b=_aptb_room(r)
    if any(q[0]==r for q in _beds()):return 1
    bed=_aptb_asset('B075QG3JWL','C_bed',(22.7,12.65,lo[2]),(1.6,2.05,1.05));bed.name=f'apt_SpareBed({r})'
    _aptb_remove(_aptb_in(r,('apt_Wardrobe(',)))
    for k,x in enumerate([21.65,23.75]):
        tb=_ra().abo('sidetable',45+k,x,13.25,lo[2],0,fit=(.4,.4,.5))
        if tb is None:raise RuntimeError('Bedside table unavailable')
        tb.name=f'aptb_C_bedside{k}';bpy.context.view_layer.update();aa,bb=_bb(tb)
        lamp=_ra().abo('tablelamp',55+k,x,13.25,bb[2],0,fit=(.22,.22,.38))
        if lamp is None:raise RuntimeError('Bedside lamp unavailable')
        lamp.name=f'aptb_C_bedlamp{k}'
    # Run the established bedding pipeline only on the recovered room.
    saved=globals()['_rooms'];globals()['_rooms']=lambda:{r:(lo,hi,'bedroom')}
    try:
        _bedding(st,stats);_bedding_layers(st,stats);_r2_ray_bedding(st,stats);_r2_seat(st,stats);_aptb_recovered_pillows(r)
    finally:globals()['_rooms']=saved
    _aptb_box('C_bedrug',(22.7,12.0,lo[2]+.008),(2.25,2.8,.012),_aptb_mat('natural_rug',(.42,.35,.25),.95),.007);return 5


def _aptb_yellow_boards():
    mat=_aptb_wood('yellow_boards',(.68,.39,.014));nt=mat.node_tree;n=nt.nodes;l=nt.links
    tc=n.new('ShaderNodeTexCoord');sep=n.new('ShaderNodeSeparateXYZ');l.new(tc.outputs['Object'],sep.inputs[0]);mult=n.new('ShaderNodeMath');mult.operation='MULTIPLY';mult.inputs[1].default_value=1/.15;l.new(sep.outputs['X'],mult.inputs[0]);fract=n.new('ShaderNodeMath');fract.operation='FRACT';l.new(mult.outputs[0],fract.inputs[0]);less=n.new('ShaderNodeMath');less.operation='LESS_THAN';less.inputs[1].default_value=.018;l.new(fract.outputs[0],less.inputs[0]);mix=n.new('ShaderNodeMixRGB');mix.inputs[2].default_value=(.11,.065,.005,1);bs=n.get('Principled BSDF');woodlink=bs.inputs['Base Color'].links[0].from_socket;l.new(woodlink,mix.inputs[1]);l.new(less.outputs[0],mix.inputs[0]);l.new(mix.outputs[0],bs.inputs['Base Color']);return mat


def _aptb_recovered_pillows(r):
    """Two supported sleeping pillows: broad underside contact, no floating six-pillow stack."""
    bed=next(q for q in _beds() if q[0]==r)
    r,lo,hi,cx,cy,ax,hd,L,W,zt=bed
    _aptb_remove([o for o in bpy.data.objects if o.name.startswith(PILL) and f'({r}|' in o.name])
    cloth=[o for o in bpy.data.objects if o.type=='MESH' and o.get('pkg_h_room')==r]
    trees=_surf_trees(cloth);base=_surf_trees([o for o in bpy.data.objects if o.name==f'apt_SpareBed({r})'])
    if len(cloth)!=4:raise RuntimeError('Recovered pillows require contact-tested duvet layers')
    saved=_LEAN[0];_LEAN[0]=(0,0);mat=_aptb_mat('recovered_linen',(.78,.75,.68),.9);records=[]
    try:
        for k,sign in enumerate([-1,1]):
            across=sign*W/4;along=L/2-.72
            px,py=(cx+hd*along,cy+across) if ax else (cx+across,cy+hd*along)
            o=_smooth_pillow(f'apt_Pillow({r}|{k})',mat,px,py,0,.5 if ax else .7,.7 if ax else .5,.13,seed=110+k,lump=.004)
            close=0;gaps=[]
            for v in o.data.vertices:
                x,y,z=v.co;s=_surf_z(trees,x,y,zt+.25)
                if s is None:s=_surf_z(base,x,y,zt+.04)
                if s is None:raise RuntimeError('Pillow has no bed support')
                ex=abs((x-px)/(.25 if ax else .35));ey=abs((y-py)/(.35 if ax else .25));edge=min(1,max(ex,ey))
                if z<0:
                    gap=.003+.02*edge**6;v.co.z=s+gap;gaps.append(gap);close+=gap<.009
                else:v.co.z=s+.03+1.3*z
            o.data.update();o['pkg_h_broad_contact_vertices']=close
            if close<150:raise RuntimeError('Insufficient pillow underside contact')
            records.append({'name':o.name,'contact_vertices_under_9mm':close,'minimum_gap_m':min(gaps)})
    finally:_LEAN[0]=saved
    return records


# pkg_h_aptc: reference-directed revisions, enabled separately after CPU smoke.
_APTC_ENABLED = ('p8_01', 'p8_02', 'p8_03', 'p8_04', 'p8_05', 'p8_06', 'p8_07', 'p8_08', 'p8_09', 'p8_10', 'p8_11', 'p8_12', 'p8_13', 'p8_14', 'p8_15')


def _aptc_mat(name, rgb, rough=.6, metal=0):
    return _aptb_mat('aptc_'+name, rgb, rough, metal)


def _aptc_box(name, pos, size, mat, bevel=.003):
    # Direct meshes avoid a full dependency-graph update for every joinery strip.
    x,y,z=(v/2 for v in size)
    vs=[(-x,-y,-z),(-x,-y,z),(-x,y,-z),(-x,y,z),(x,-y,-z),(x,-y,z),(x,y,-z),(x,y,z)]
    fs=[(0,4,6,2),(1,3,7,5),(0,1,5,4),(2,6,7,3),(0,2,3,1),(4,5,7,6)]
    me=bpy.data.meshes.new('aptc_'+name);me.from_pydata(vs,[],fs);me.materials.append(mat)
    o=bpy.data.objects.new('aptc_'+name,me);bpy.context.scene.collection.objects.link(o);o.location=pos
    if bevel:
        q=o.modifiers.new('Rounded joinery edges','BEVEL');q.width=bevel;q.segments=3
        o.modifiers.new('Weighted joinery normals','WEIGHTED_NORMAL')
    return o


def _aptc_fabric(name,rgb):
    m=_aptc_mat(name,rgb,.83)
    if not m.get('cloth'):
        n=m.node_tree.nodes;l=m.node_tree.links;geo=n.new('ShaderNodeNewGeometry');no=n.new('ShaderNodeTexNoise');no.inputs['Scale'].default_value=600;l.new(geo.outputs['Position'],no.inputs['Vector']);bu=n.new('ShaderNodeBump');bu.inputs['Distance'].default_value=.0003;bu.inputs['Strength'].default_value=.2;l.new(no.outputs['Fac'],bu.inputs['Height']);l.new(bu.outputs[0],n.get('Principled BSDF').inputs['Normal']);m['cloth']=1
    return m


def _aptc_blue(wall=True):
    import numpy as np
    name='botanical_wall' if wall else 'botanical_cloth';m=_aptc_mat(name,(.78,.76,.69),.75)
    if m.get('dense_botanical'):return m
    npx=768;yy,xx=np.mgrid[0:npx,0:npx].astype(float)/npx
    pixels=np.ones((npx,npx,4),dtype=np.float32);pixels[:,:,:3]=(.79,.77,.70)
    ink=np.zeros((npx,npx),dtype=bool);rng=random.Random(413)
    # Continuous climbing branches, with dense overlapping leaf and rose clusters.
    for k in range(6):
        shift=k/6;curve=(shift+.11*np.sin(yy*math.tau+.7*k))%1
        d=(xx-curve+.5)%1-.5;mask=np.abs(d)<.004
        pixels[mask,:3]=(.17,.27,.39);ink|=mask
        for j in range(15):
            cy=(j+.2*(k%2))/15;cx=(shift+.11*math.sin(cy*math.tau+.7*k))%1
            for sg in [-1,1]:
                dx=(xx-(cx+sg*.038)+.5)%1-.5;dy=(yy-(cy+.022)+.5)%1-.5
                u=.8*dx+sg*.6*dy;v=-sg*.6*dx+.8*dy;leaf=(u/.047)**2+(v/.016)**2<1
                pixels[leaf,:3]=(.22,.32,.45);ink|=leaf
    for k in range(13):
        cx,cy=rng.random(),rng.random();dx=(xx-cx+.5)%1-.5;dy=(yy-cy+.5)%1-.5;rr=np.sqrt(dx*dx+dy*dy);ang=np.arctan2(dy,dx)
        radius=.067+.010*np.cos(7*ang);rose=rr<radius;ink|=rose;pixels[rose,:3]=(.29,.39,.51)
        for rad,phase in [(.053,.7),(.039,1.2),(.023,1.8)]:
            edge=np.abs(rr-rad-.006*np.sin(7*ang+phase))<.003
            pixels[edge&rose,:3]=(.105,.20,.34)
        core=rr<.010;pixels[core,:3]=(.105,.20,.34)
    coverage=float(ink.mean())
    if not .25<coverage<.65:raise RuntimeError('Botanical density out of range '+str(coverage))
    im=bpy.data.images.new('aptc_dense_blue_botanical',width=npx,height=npx);im.colorspace_settings.name='Non-Color';im.pixels.foreach_set(pixels.ravel());im.pack()
    nt=m.node_tree;N=nt.nodes;L=nt.links;b=N.get('Principled BSDF');geo=N.new('ShaderNodeNewGeometry');sp=N.new('ShaderNodeSeparateXYZ');L.new(geo.outputs['Position'],sp.inputs[0]);vec=N.new('ShaderNodeCombineXYZ')
    if wall:
        add=N.new('ShaderNodeMath');add.operation='ADD';L.new(sp.outputs['X'],add.inputs[0]);L.new(sp.outputs['Y'],add.inputs[1]);L.new(add.outputs[0],vec.inputs['X']);L.new(sp.outputs['Z'],vec.inputs['Y'])
    else:L.new(sp.outputs['X'],vec.inputs['X']);L.new(sp.outputs['Y'],vec.inputs['Y'])
    scale=N.new('ShaderNodeVectorMath');scale.operation='SCALE';scale.inputs['Scale'].default_value=1/.90;L.new(vec.outputs[0],scale.inputs[0]);tex=N.new('ShaderNodeTexImage');tex.image=im;tex.extension='REPEAT';L.new(scale.outputs[0],tex.inputs['Vector'])
    if wall:
        cmp=N.new('ShaderNodeMath');cmp.operation='LESS_THAN';cmp.inputs[1].default_value=1.19;L.new(sp.outputs['Z'],cmp.inputs[0]);mix=N.new('ShaderNodeMixRGB');L.new(cmp.outputs[0],mix.inputs[0]);L.new(tex.outputs['Color'],mix.inputs[1]);mix.inputs[2].default_value=(.82,.80,.75,1);L.new(mix.outputs[0],b.inputs['Base Color'])
    else:L.new(tex.outputs['Color'],b.inputs['Base Color'])
    m['dense_botanical']=1;m['ink_coverage']=coverage;m['repeat_m']=.90;return m


def _aptc_pillows(st,stats):
    _r2_ray_bedding(st,stats)
    if stats['pkg_h_ray_bedding']['fail']:raise RuntimeError(str(stats['pkg_h_ray_bedding']['fail']))
    records=[]
    for r,lo,hi,cx,cy,ax,hd,L,W,zt in _beds():
        _aptb_remove([o for o in bpy.data.objects if o.name.startswith(PILL) and f'({r}|' in o.name])
        base=[o for o in bpy.data.objects if o.type=='MESH' and ((o.name.startswith('MattressFactory') and _in_box(o,lo,hi)) or o.name==f'apt_SpareBed({r})')]
        layers=[o for o in bpy.data.objects if o.get('pkg_h_room')==r and o.get('pkg_h_kind') in ('Duvet','Throw','Fold','Runner')]
        if len(layers)!=4:raise RuntimeError('Four supported cloth layers required for '+r)
        support=_surf_trees(layers);matt=_surf_trees(base);made=[];minclose=100000
        for row in range(2):
            for k,sg in enumerate([-1,1]):
                cross=sg*W*.235;along=L/2-(.68 if row==0 else 1.03)
                px,py=(cx+hd*along,cy+cross) if ax else (cx+cross,cy+hd*along)
                rgb=(.76,.73,.67) if row==0 else ((.10,.105,.11) if lo[0]<12 else (.18,.27,.40))
                sx,sy=(.42,.64) if ax else (.64,.42)
                if row:sx*=.88;sy*=.88
                o=_smooth_pillow(f'aptc_Pillow({r}|{row}_{k})',_aptc_fabric('case_'+str(lo[0]<12)+'_'+str(row),rgb),px,py,0,sx,sy,.10,seed=911+row*2+k,lump=.004)
                close=0
                for v in o.data.vertices:
                    x,y,z=v.co;s=_surf_z(support,x,y,zt+.65)
                    if s is None:s=_surf_z(matt,x,y,zt+.04)
                    if s is None:raise RuntimeError('Pillow support missing in '+r)
                    edge=min(1,max(abs((x-px)/(sx/2)),abs((y-py)/(sy/2))))
                    if z<0:
                        gap=.003+.018*edge**6;v.co.z=s+gap;close+=gap<.009
                    else:v.co.z=s+.024+1.25*z
                o.data.update();o['pkg_h_room']=r;o['pkg_h_kind']='Pillow';o['aptc_contact_vertices']=close
                if close<150:raise RuntimeError('Insufficient broad pillow contact')
                made.append(o);minclose=min(minclose,close)
            bpy.context.view_layer.update();support=_surf_trees(layers+made)
        records.append({'room':r,'pillows':len(made),'min_contact_vertices':minclose,'cloth_gap_m':max(o['pkg_h_gap_max_m'] for o in layers)})
    stats['aptc_pillow_proof']=records;return len(records)


def _aptc_curtains():
    n=_aptb_open_curtains()
    for o in bpy.data.objects:
        if o.name.startswith(('apt_DrapeL','apt_DrapeR')):
            a,b=_bb(o)
            if (a[0]+b[0])/2<12:_set_slots(o,_aptc_fabric('charcoal_drapes',(.055,.05,.045)))
    return n


def _aptc_pleat(r,x,y,bottom=1.96,diameter=.50,height=.32,cord=True):
    import bmesh
    lo,hi,a,b=_aptb_room(r);rad=diameter/2;bm=bmesh.new();rings=[]
    for j in range(9):
        t=j/8;radius=rad*(1-.38*t);z=bottom+t*height
        ring=[]
        for i in range(160):
            theta=i*math.tau/160;rr=radius*(1+.045*math.cos(40*theta));ring.append(bm.verts.new((x+rr*math.cos(theta),y+rr*math.sin(theta),z)))
        rings.append(ring)
    for j in range(8):
        for i in range(160):bm.faces.new((rings[j][i],rings[j][(i+1)%160],rings[j+1][(i+1)%160],rings[j+1][i]))
    bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces));me=bpy.data.meshes.new('aptc_pleated_linen');bm.to_mesh(me);bm.free();o=bpy.data.objects.new('aptc_PleatedShade('+r+')',me);bpy.context.scene.collection.objects.link(o)
    mat=_aptc_fabric('pendant_linen',(.75,.71,.62));nt=mat.node_tree
    if not mat.get('translucent'):
        n=nt.nodes;l=nt.links;tr=n.new('ShaderNodeBsdfTranslucent');tr.inputs[0].default_value=(.8,.75,.64,1);mix=n.new('ShaderNodeMixShader');mix.inputs[0].default_value=.32;l.new(n.get('Principled BSDF').outputs[0],mix.inputs[1]);l.new(tr.outputs[0],mix.inputs[2]);l.new(mix.outputs[0],n.get('Material Output').inputs['Surface']);mat['translucent']=1
    me.materials.append(mat);so=o.modifiers.new('Thin sewn linen','SOLIDIFY');so.thickness=.001
    if cord:_aptc_box(r+'_pendant_cord',(x,y,(bottom+height+_zc(r,lo))/2),(.005,.005,max(.015,_zc(r,lo)-bottom-height)),_aptc_mat('cord',(.06,.055,.05)),.001)
    _globe('aptc_Bulb('+r+')',x,y,bottom+.15,_emit('aptc_bulb',(1,.78,.48),3),r=.025);_light('aptc_PendantLight('+r+')','POINT',(x,y,bottom+.15),18,(1,.80,.57),r=.025)
    o['aptc_pleats']=40;return o


def _aptc_smallplant(pos,name,h=.30):
    o=_aptb_asset('HSSD_4dbb221926b856e5c1c07a26b133690d47cd818d','aptc_'+name,pos,(h*.7,h*.7,h));_aptb_fix_leaf([o]);return o


def _aptc_sideboard_A():
    r='living-room_0/0';lo,hi,a,b=_aptb_room(r)
    old=_aptb_in(r,('aptb_'+r+'_sideboard','AboDresserFactory'))
    cabinet=_aptb_asset('HSSD_a7a9b8d2ae756986014a94885ed86da2ba797214','aptc_A_sideboard',(2.70,b[1]-.25,lo[2]),(2.10,.46,.74));bpy.context.view_layer.update();aa,bb=_bb(cabinet)
    if bb[0]-aa[0]<1.7 or bb[1]>b[1]-.015:raise RuntimeError('A sideboard dimensions/clearance failed')
    lamp=_aptb_asset('B0825DKP92','aptc_A_sideboard_lamp',(3.25,b[1]-.25,bb[2]),(.25,.25,.45));_aptc_smallplant((2.10,b[1]-.25,bb[2]),'A_sideboard_green',.32)
    _aptb_remove(old);return 3


def _aptc_white_case(r,name,cx,cy,w=1.60):
    # Real furniture asset with modeled door/pull detail; preserve its actual joinery.
    lo,hi,a,b=_aptb_room(r)
    o=_aptb_asset('HSSD_e4bf06896b67fc56bbded3bbd2086ad6dcdb7746','aptc_'+name,(cx,cy,lo[2]),(w+.05,.51,.84),math.pi)
    _set_big_slot(o,_aptc_mat('white_cabinet_enamel',(.78,.76,.70),.4));bpy.context.view_layer.update();aa,bb=_bb(o)
    if aa[1]<a[1]+.015 or bb[1]>b[1]-.015:raise RuntimeError('Sideboard crosses wall')
    return o


def _aptc_oval(r):
    lo,hi,a,b=_aptb_room(r);old=_aptb_in(r,('AboCoffeeFactory',))
    o=_aptb_asset('B01M4OYBOI','aptc_B_oval_coffee',(14.75,5.85,lo[2]),(1.10,.65,.44));_set_big_slot(o,_aptc_mat('white_table',(.81,.79,.73),.4));bpy.context.view_layer.update();aa,bb=_bb(o)
    for q in _aptb_in(r,('apt_Table','apt_Coffee','Food','Tray','Fruit','Candle','Real_hssd')):
        qa,qb=_bb(q)
        if abs((qa[0]+qb[0])/2-14.8)<.7 and abs((qa[1]+qb[1])/2-6)<.7:q.matrix_world.translation+=Vector((-.067,-.15,bb[2]-qa[2]+.002))
    _aptb_remove(old)
    _aptb_asset('HSSD_21551881391c2b21c2e1358effa7d6b69cbd435f','aptc_B_table_plate',(14.75,5.85,bb[2]),(.24,.24,.025));_aptc_smallplant((14.5,5.85,bb[2]),'B_table_green',.25);return 3


def _aptc_wainscot(r):
    lo,hi,a,b=_aptb_room(r);mat=_aptc_mat('white_panel_paint',(.82,.80,.75),.5);n=0
    cas=[_bb(o) for o in bpy.data.objects if o.type=='MESH' and o.name.startswith('DoorCasingFactory')]
    for side in 'SNWE':
        axis=0 if side in 'SN' else 1;cross=1-axis;face=a[cross] if side in 'SW' else b[cross];start=a[axis]+.025;end=b[axis]-.025
        cuts=sorted((c[0][axis]-.04,c[1][axis]+.04) for c in cas if abs((c[0][cross]+c[1][cross])/2-face)<.35 and c[1][axis]>start and c[0][axis]<end)
        if r.startswith('bathroom') and side in 'SN':cuts=sorted(cuts+[(13.70,15.10)])
        segs=[];t=start
        for c0,c1 in cuts:
            if c0>t+.06:segs.append((t,min(c0,end)))
            t=max(t,c1)
        if t<end-.06:segs.append((t,end))
        for j,(u,v) in enumerate(segs):
            q=face+(.018 if side in 'SW' else -.018);center=[0,0,lo[2]+.55];center[axis]=(u+v)/2;center[cross]=q;size=[0,0,.96];size[axis]=v-u;size[cross]=.025
            _aptc_box(r+side+str(j)+'panel',center,size,mat)
            center[2]=lo[2]+1.05;size[2]=.045;_aptc_box(r+side+str(j)+'cap',center,size,mat)
            n+=2
    return n


def _aptc_stone():
    m=_aptc_mat('pale_stone',(.55,.53,.49),.38)
    if not m.get('tiles'):
        n=m.node_tree.nodes;l=m.node_tree.links;g=n.new('ShaderNodeNewGeometry');br=n.new('ShaderNodeTexBrick');br.offset=0;br.inputs['Scale'].default_value=1;br.inputs['Brick Width'].default_value=.60;br.inputs['Row Height'].default_value=.60;br.inputs['Mortar Size'].default_value=.002;br.inputs['Color1'].default_value=(.55,.53,.49,1);br.inputs['Color2'].default_value=(.51,.50,.46,1);br.inputs['Mortar'].default_value=(.32,.31,.29,1);l.new(g.outputs['Position'],br.inputs['Vector']);l.new(br.outputs['Color'],n.get('Principled BSDF').inputs['Base Color']);m['tiles']=1
    return m


def _aptc_mirror(r,x,y,z,w=.65,h=.95,positive_y=False):
    # A real elliptical glass face, with a distinct 3D brass frame.
    from mathutils import Matrix
    mat=_aptc_mat('mirror',(.8,.82,.84),.02,1);gold=_aptc_mat('brass',(.5,.30,.08),.28,1)
    n=96;vs=[(x,y,z)]+[(x+w/2*math.cos(i*math.tau/n),y,z+h/2*math.sin(i*math.tau/n)) for i in range(n)];fs=[(0,i+1,(i+1)%n+1) for i in range(n)];me=bpy.data.meshes.new('aptc_oval_mirror');me.from_pydata(vs,[],[tuple(reversed(f)) for f in fs] if positive_y else fs);me.materials.append(mat);o=bpy.data.objects.new('aptc_Mirror('+r+')',me);bpy.context.scene.collection.objects.link(o)
    # Curve frame follows the true oval, rather than a flat printed border.
    cu=bpy.data.curves.new('aptc_oval_frame','CURVE');cu.dimensions='3D';cu.bevel_depth=.009;cu.bevel_resolution=3;s=cu.splines.new('POLY');s.points.add(n-1)
    for i,p in enumerate(s.points):p.co=(x+w/2*math.cos(i*math.tau/n),y-.004,z+h/2*math.sin(i*math.tau/n),1)
    s.use_cyclic_u=True;q=bpy.data.objects.new('aptc_OvalFrame('+r+')',cu);bpy.context.scene.collection.objects.link(q);q.data.materials.append(gold);return o


def _aptc_feature(key,st,stats):
    if key=='p8_01':return _aptc_pillows(st,stats)
    if key=='p8_02':return _aptc_curtains()
    if key=='p8_03':
        n=0
        for r,(lo,hi,t) in _rooms().items():
            if lo[0]>=12 and t in ('bedroom','living-room','kitchen','hallway'):
                o=bpy.data.objects.get(r+'.wall')
                if o:_set_slots(o,_aptc_blue());n+=1
        return n
    if key=='p8_04':
        n=0
        for o in bpy.data.objects:
            if o.get('pkg_h_room') in ('bedroom_0/2','bedroom_0/3'):
                if o.get('pkg_h_kind') in ('Duvet','Pillow'):_set_slots(o,_aptc_blue(False));n+=1
                elif o.get('pkg_h_kind') in ('Throw','Runner'):_set_slots(o,_aptc_fabric('blue_woven_throw',(.15,.22,.32)));n+=1
        return n
    if key=='p8_05':
        for r in ['bedroom_0/2','bedroom_0/3']:
            lo,hi,a,b=_aptb_room(r);_aptc_pleat(r,(a[0]+b[0])/2,(a[1]+b[1])/2)
        return 2
    if key=='p8_06':return _aptc_sideboard_A()
    if key=='p8_07':
        r='living-room_0/1';old=_aptb_in(r,('AboArmchairFactory',));lo,hi,a,b=_aptb_room(r)
        for plant in _aptb_in(r,('Real_hssd(HSSD_09ca84e',)):
            aa,bb=_bb(plant);plant.matrix_world.translation+=Vector((12.55-(aa[0]+bb[0])/2,5.50-(aa[1]+bb[1])/2,lo[2]+.002-aa[2]))
        _aptb_asset('B082QBBY7R','aptc_B_cream_chair',(13.25,6.90,lo[2]),(.90,.95,.90),.95);_aptb_remove(old);return 1
    if key=='p8_08':
        r='living-room_0/1';old=_aptb_in(r,('AboDresserFactory',));_aptc_white_case(r,'B_white_sideboard',14.4,4.43);_aptb_remove(old);return 1
    if key=='p8_09':return _aptc_oval('living-room_0/1')
    if key=='p8_10':
        r='living-room_0/1';_aptc_pleat(r,14.75,6.0);o=bpy.data.objects.get('aptb_aptc_B_white_sideboard')
        if o is None:raise RuntimeError('B lamps require the new sideboard')
        bpy.context.view_layer.update();a,b=_bb(o)
        for k,x in enumerate([13.90,14.90]):_aptb_asset('B0824FBQF3','aptc_B_lamp'+str(k),(x,4.43,b[2]),(.25,.25,.45))
        return 3
    if key=='p8_11':
        r='hallway_0/2';_set_slots(bpy.data.objects[r+'.wall'],_aptc_blue());_set_slots(bpy.data.objects[r+'.floor'],_aptc_stone());return _aptc_wainscot(r)
    if key=='p8_12':
        r='hallway_0/2';lo,hi,a,b=_aptb_room(r);old=_aptb_in(r,('apt_R2Console','apt_HallConsole','apt_R2Mirror','Real_nightstand','apt_Console','apt_Mirror','apt_Corridor_console','Real_hssd(HSSD_04c4d866'))
        o=_aptb_asset('HSSD_e4bf06896b67fc56bbded3bbd2086ad6dcdb7746','aptc_hall_white_console',(9.07,a[1]+.28,lo[2]),(1.65,.51,.84),math.pi);_set_big_slot(o,_aptc_mat('white_cabinet_enamel',(.78,.76,.70),.4));_aptc_mirror(r,9.07,a[1]+.04,lo[2]+1.65,positive_y=True)
        _aptb_remove(old)
        bpy.context.view_layer.update();aa,bb=_bb(o)
        _aptc_smallplant((8.65,a[1]+.28,bb[2]),'hall_console_green',.30)
        for prop in _aptb_in(r,('Real_hssd(HSSD_069ac037',)):
            pa,pb=_bb(prop);prop.location.z+=bb[2]-pa[2]+.002
        return 3
    if key=='p8_13':
        r='hallway_0/2';lo,hi,a,b=_aptb_room(r)
        for x in [6,12]:_aptc_pleat(r,x,2.0,1.96)
        old=_aptb_in(r,('Real_hssd(HSSD_09ca84e','apt_Corridor_plant'))
        for k,o in enumerate(old):
            aa,bb=_bb(o);_aptc_smallplant(((aa[0]+bb[0])/2,min(b[1]-.35,max(a[1]+.35,(aa[1]+bb[1])/2)),lo[2]),'hall_tree'+str(k),1.45)
        _aptb_remove(old)
        console=bpy.data.objects['aptb_aptc_hall_white_console'];bpy.context.view_layer.update();ca,cb=_bb(console)
        _aptb_asset('B0824FBQF3','aptc_hall_console_lamp',(9.5,a[1]+.28,cb[2]),(.25,.25,.43))
        return 3+len(old)
    if key=='p8_14':
        r='bathroom_0/1';_set_slots(bpy.data.objects[r+'.wall'],_aptc_bath_blue());n=_aptc_wainscot(r)
        for room in ['bathroom_0/0',r]:_set_slots(bpy.data.objects[room+'.floor'],_plank('aptc_bath_timber',(.48,.34,.20),(.40,.28,.16)))
        lo,hi,a,b=_aptb_room(r)
        _aptc_pleat(r,12.40,a[1]+.20,1.60,diameter=.19,height=.18,cord=False)
        brass=_aptc_mat('brass',(.50,.30,.08),.28,1)
        _aptc_box('bath_sconce_plate',(12.40,a[1]+.025,1.62),(.07,.018,.14),brass,.008)
        _aptc_box('bath_sconce_arm',(12.40,a[1]+.12,1.61),(.012,.20,.012),brass,.005)
        _aptc_botanical_art(r,15.45,a[1]+.045,1.82)
        return n+3
    if key=='p8_15':return _aptc_kitchen_dress()
    raise KeyError(key)


def _aptc_kitchen_dress():
    n=0
    for r in ['kitchen_0/0','kitchen_0/1']:
        lo,hi,a,b=_aptb_room(r)
        _aptb_remove([o for o in bpy.data.objects if o.name.startswith('aptb_'+r+'_dish')])
        for k in range(4):
            for j in range(3):
                shelf=bpy.data.objects.get(f'aptb_{r}_upper{k}_shelf{j}')
                if shelf is None:raise RuntimeError('Glazed shelf missing')
                bpy.context.view_layer.update();sa,sb=_bb(shelf);w=sb[0]-sa[0];y=(sa[1]+sb[1])/2-.02
                for q in range(4):
                    x=sa[0]+(q+.5)*w/4
                    aid=['HSSD_0128475579600f804ec7ef1cf8a212622760cfd1','HSSD_036edf04844210dae3f5afc59165ad4955b3510b','HSSD_21551881391c2b21c2e1358effa7d6b69cbd435f','HSSD_0128475579600f804ec7ef1cf8a212622760cfd1'][q]
                    _aptb_asset(aid,f'aptc_{r}_dish{k}_{j}_{q}',(x,y,sb[2]+.002),(.17,.17,.17 if q!=2 else .026));n+=1
        run=bpy.data.objects.get('apt_KitchenRun('+r+')');trees=_surf_trees([run]) if run else []
        x=a[0]+1.15;y=b[1]-.36;z=_surf_z(trees,x,y,lo[2]+1.2)
        if z is None:raise RuntimeError('Counter support missing '+r)
        _aptc_smallplant((x,y,z+.002),r+'_counter_green',.35)
        for aid,name,dx,size in [('HSSD_c139234bf8464898e67b064e1726440a3e84b0b6','board',.45,(.24,.15,.28)),('HSSD_695e49c5fe19b4a0e70078f755a2dece95533d86','holder',.75,(.14,.14,.17))]:_aptb_asset(aid,'aptc_'+r+name,(x+dx,y,z+.002),size)
        for k in range(3):_aptb_asset('HSSD_3b63f000011404011c4aeb3f19bb04a112535634','aptc_'+r+'spoon'+str(k),(x+.72+k*.03,y,z+.12),(.035,.035,.22));n+=1
    r='kitchen_0/0';lo,hi,a,b=_aptb_room(r);old=bpy.data.objects.get('aptb_kitchen_clock')
    if old:bpy.data.objects.remove(old,do_unlink=True)
    _aptb_asset('HSSD_20c32bc8e148545c59afd79fdfe8ea3155073179','aptc_kitchen_clock',(b[0]-.035,8.30,1.62),(.05,.28,.28),-math.pi/2);return n+7


def _aptc_apply(st,stats):
    style=next((k for k,v in STYLES.items() if v is st),None)
    if style is None:return
    done=set(str(bpy.context.scene.get('pkg_h_aptc_done','')).split(','))
    for key in _APTC_ENABLED:
        if not key.startswith(style+'_') or key in done:continue
        try:
            result=_aptc_feature(key,st,stats)
            if not result:raise RuntimeError('Empty feature '+key)
            done.add(key);bpy.context.scene['pkg_h_aptc_done']=','.join(sorted(done));stats['pkg_h_aptc_'+key]=result
        except Exception as ex:
            import traceback
            traceback.print_exc();stats['pkg_h_aptc_'+key+'_error']=repr(ex)


def _aptc_bath_blue():
    m=bpy.data.materials.get('aptc_bath_dry_toile')
    if m:return m
    m=_aptc_blue().copy();m.name='aptc_bath_dry_toile';n=m.node_tree.nodes;l=m.node_tree.links;bs=n.get('Principled BSDF');old=bs.inputs['Base Color'].links[0].from_socket
    geo=n.new('ShaderNodeNewGeometry');sep=n.new('ShaderNodeSeparateXYZ');l.new(geo.outputs['Position'],sep.inputs[0]);gt=n.new('ShaderNodeMath');gt.operation='GREATER_THAN';gt.inputs[1].default_value=13.70;l.new(sep.outputs['X'],gt.inputs[0]);lt=n.new('ShaderNodeMath');lt.operation='LESS_THAN';lt.inputs[1].default_value=15.10;l.new(sep.outputs['X'],lt.inputs[0]);mul=n.new('ShaderNodeMath');mul.operation='MULTIPLY';l.new(gt.outputs[0],mul.inputs[0]);l.new(lt.outputs[0],mul.inputs[1]);mix=n.new('ShaderNodeMixRGB');l.new(mul.outputs[0],mix.inputs[0]);l.new(old,mix.inputs[1]);mix.inputs[2].default_value=(.72,.71,.67,1);l.new(mix.outputs[0],bs.inputs['Base Color']);return m


def _aptc_botanical_art(r,x,y,z):
    cream=_aptc_mat('print_paper',(.80,.77,.69),.9);wood=_aptc_mat('print_frame',(.42,.29,.13),.45);blue=_aptc_mat('botanical_ink',(.09,.19,.31),.9)
    _aptc_box('BotanicalPaper('+r+')',(x,y,z),(.27,.012,.39),cream,.001)
    for dx,dz,sx,sz in [(-.145,0,.02,.43),(.145,0,.02,.43),(0,-.205,.27,.02),(0,.205,.27,.02)]:_aptc_box('BotanicalFrame('+r+')',(x+dx,y+.006,z+dz),(sx,.025,sz),wood,.002)
    for k in range(11):
        t=k/10;zz=z-.16+t*.31;xx=x+.025*math.sin(t*math.pi)
        _aptc_box('botanical_stem'+str(k),(xx,y+.007,zz),(.0015,.001,.034),blue,0)
        for sg in [-1,1]:
            cx=xx+sg*.037;cz=zz+.012;vs=[(cx+.035*math.cos(i*math.tau/24),y+.008,cz+.012*math.sin(i*math.tau/24)+sg*.018*math.cos(i*math.tau/24)) for i in range(24)];me=bpy.data.meshes.new('botanical_leaf');me.from_pydata(vs,[],[tuple(range(24))]);me.materials.append(blue);o=bpy.data.objects.new('aptc_BotanicalLeaf('+r+')',me);bpy.context.scene.collection.objects.link(o)


# pkg_h_aptd: one isolated reference item per enabled feature.
_APTD_ENABLED = ('p8_01', 'p8_02', 'p8_03', 'p8_04', 'p8_05', 'p8_06', 'p8_07', 'p8_08', 'p8_09', 'p8_10', 'p8_11', 'p8_12', 'p8_13', 'p8_14', 'p8_15', 'p7_01', 'p7_02', 'p7_03', 'p7_04', 'p7_05', 'p7_06', 'p7_07', 'p7_08', 'p7_09', 'p7_10', 'p7_11', 'p7_12', 'p7_13', 'p7_14', 'p7_15', 'p9_01', 'p9_02', 'p9_03', 'p9_04', 'p9_05', 'p9_06', 'p9_07', 'p9_08', 'p9_09', 'p9_10', 'p9_11', 'p9_12', 'p9_13', 'p9_14', 'p9_15')


def _aptd_obj(name):
    o=bpy.data.objects.get(name)
    if o is None:
        raise RuntimeError('Required reference object missing: '+name)
    return o


def _aptd_fit(o,center,size):
    from mathutils import Matrix
    bpy.context.view_layer.update()
    a,b=_bb(o)
    mid=Vector([(a[i]+b[i])/2 for i in range(3)])
    dims=[b[i]-a[i] for i in range(3)]
    if min(dims)<1e-6:
        raise RuntimeError('Degenerate asset '+o.name)
    target=Vector((center[0],center[1],center[2]+size[2]/2))
    o.matrix_world=Matrix.Translation(target)@Matrix.Diagonal(Vector([size[i]/dims[i] for i in range(3)]+[1]))@Matrix.Translation(-mid)@o.matrix_world
    bpy.context.view_layer.update()
    return o


def _aptd_asset(aid,name,pos,size,yaw=0):
    o=_aptb_asset(aid,'aptd_'+name,pos,size,yaw)
    return _aptd_fit(o,pos,size)


def _aptd_move(o,x,y,z,turn=0):
    from mathutils import Matrix
    a,b=_bb(o)
    c=Vector(((a[0]+b[0])/2,(a[1]+b[1])/2,a[2]))
    o.matrix_world=Matrix.Translation(Vector((x,y,z)))@Matrix.Rotation(turn,4,'Z')@Matrix.Translation(-c)@o.matrix_world
    bpy.context.view_layer.update()


def _aptd_weave(name,rgb):
    mat=_aptc_fabric('aptd_'+name,rgb)
    bs=mat.node_tree.nodes.get('Principled BSDF')
    bs.inputs['Roughness'].default_value=.88
    return mat


def _aptd_rug(o,kind='natural'):
    mat=_aptd_weave('rug_'+kind,(.40,.31,.20))
    if not mat.get('aptd_pattern'):
        n=mat.node_tree.nodes
        l=mat.node_tree.links
        bs=n.get('Principled BSDF')
        tc=n.new('ShaderNodeTexCoord')
        if kind=='checker':
            pat=n.new('ShaderNodeTexChecker')
            pat.inputs['Scale'].default_value=14
            pat.inputs['Color1'].default_value=(.46,.33,.20,1)
            pat.inputs['Color2'].default_value=(.065,.033,.02,1)
            sep=n.new('ShaderNodeSeparateXYZ');vec=n.new('ShaderNodeCombineXYZ')
            l.new(tc.outputs['Generated'],sep.inputs[0]);l.new(sep.outputs['X'],vec.inputs['X']);l.new(sep.outputs['Y'],vec.inputs['Y'])
            l.new(vec.outputs[0],pat.inputs['Vector'])
            l.new(pat.outputs['Color'],bs.inputs['Base Color'])
        elif kind=='stripe':
            pat=n.new('ShaderNodeTexWave')
            pat.bands_direction='Y'
            pat.inputs['Scale'].default_value=12
            ramp=n.new('ShaderNodeValToRGB')
            ramp.color_ramp.interpolation='CONSTANT'
            ramp.color_ramp.elements[0].position=.92
            ramp.color_ramp.elements[0].color=(.60,.54,.43,1)
            ramp.color_ramp.elements[1].position=.95
            ramp.color_ramp.elements[1].color=(.22,.035,.022,1)
            l.new(tc.outputs['Generated'],pat.inputs['Vector'])
            l.new(pat.outputs['Fac'],ramp.inputs[0])
            l.new(ramp.outputs[0],bs.inputs['Base Color'])
        elif kind=='navy_border':
            sep=n.new('ShaderNodeSeparateXYZ')
            l.new(tc.outputs['Generated'],sep.inputs[0])
            masks=[]
            for axis in ['X','Y']:
                for op,threshold in [('LESS_THAN',.055),('GREATER_THAN',.945)]:
                    node=n.new('ShaderNodeMath')
                    node.operation=op
                    node.inputs[1].default_value=threshold
                    l.new(sep.outputs[axis],node.inputs[0])
                    masks.append(node.outputs[0])
            fac=masks[0]
            for sock in masks[1:]:
                node=n.new('ShaderNodeMath')
                node.operation='MAXIMUM'
                l.new(fac,node.inputs[0])
                l.new(sock,node.inputs[1])
                fac=node.outputs[0]
            mix=n.new('ShaderNodeMixRGB')
            mix.inputs[1].default_value=(.45,.35,.22,1)
            mix.inputs[2].default_value=(.018,.033,.075,1)
            l.new(fac,mix.inputs[0])
            l.new(mix.outputs[0],bs.inputs['Base Color'])
        mat['aptd_pattern']=1
    _set_slots(o,mat)
    a,b=_bb(o)
    room=next((r for r,(lo,hi,t) in _rooms().items() if _in_box(o,lo,hi)),None)
    if room:
        floor=_aptb_room(room)[0][2]
        o.location.z+=floor+.002-a[2]
    return 1


def _aptd_green(pos,name,h=.3):
    o=_aptd_asset('HSSD_17292deefa4135485bbcbcdbaa366b951ddc7075',name,pos,(h*.8,h*.65,h))
    _aptb_fix_leaf([o])
    return o


def _aptd_tableware(table,name):
    a,b=_bb(table)
    x,y,z=(a[0]+b[0])/2,(a[1]+b[1])/2,b[2]+.003
    _aptd_asset('HSSD_23b5b1fc6feeab3f96891017de6dff09d187ae51',name+'_tray',(x,y,z),(.43,.30,.035))
    for k in [-1,1]:
        _aptd_asset('HSSD_1bc20d448937a6c0c1936b28486a110f31093947',name+'_cup'+str(k),(x+k*.12,y,z+.038),(.10,.08,.10))
    _aptd_green((x,y+.21,z),name+'_green',.24)
    return 4


def _aptd_soft(sofa,name,rgb):
    a,b=_bb(sofa)
    ax=b[0]-a[0]>b[1]-a[1]
    # Find broad seat support below the cushion backs, not the top of the backrest.
    trees=_surf_trees([sofa])
    cx,cy=(a[0]+b[0])/2,(a[1]+b[1])/2
    mat=_aptd_weave(name+'_cushion',rgb)
    made=0
    for k,offset in enumerate([-.55,-.18,.20,.55]):
        px,py=(cx+offset,cy-.12) if ax else (cx-.12,cy+offset)
        z=_surf_z(trees,px,py,a[2]+.68)
        if z is None:
            continue
        pillow=_smooth_pillow('aptd_'+name+'_cushion'+str(k),mat,px,py,z+.11,.40,.38,.17,seed=391+k,lump=.009)
        aa,bb=_bb(pillow)
        pillow.location.z+=z+.003-aa[2]
        made+=1
    if made<2:
        raise RuntimeError('No clear sofa cushion support '+name)
    return made


def _aptd_coffee(old,name,pos,glass=False):
    oldtop=_bb(old)[1][2]
    aid='HSSD_01d9fff2f701af7d5d40a7a5adad5bf40d4c49c8' if glass else 'HSSD_0030aabddff541fbd378e38ae2d8597aecbfc757'
    o=_aptd_asset(aid,name,pos,(.95,.95,.40))
    if not glass:
        _set_big_slot(o,_aptc_mat('aptd_black_table',(.018,.02,.023),.22))
    # Move existing tabletop decor only when actually supported by the old top.
    a,b=_bb(old)
    for q in list(bpy.data.objects):
        if q.type!='MESH' or q in [old,o]:
            continue
        qa,qb=_bb(q)
        if a[0]<=(qa[0]+qb[0])/2<=b[0] and a[1]<=(qa[1]+qb[1])/2<=b[1] and abs(qa[2]-oldtop)<.04 and qb[2]-qa[2]<.5:
            q.location.z+=pos[2]+.403-qa[2]
    bpy.data.objects.remove(old,do_unlink=True)
    return 1


def _aptd_bedpair(r,name):
    lo,hi,a,b=_aptb_room(r)
    bed=next(v for v in _beds() if v[0]==r)
    _,_,_,cx,cy,ax,hd,L,W,zt=bed
    count=0
    lamps=_aptb_in(r,('apt_BedLamp',))
    for sign in [-1,1]:
        cross=sign*(W/2+.26)
        along=hd*(L/2-.40)
        x,y=(cx+along,cy+cross) if ax else (cx+cross,cy+along)
        if not (a[0]+.22<x<b[0]-.22 and a[1]+.22<y<b[1]-.22):
            continue
        if any(abs((_bb(o)[0][0]+_bb(o)[1][0])/2-x)<.28 and abs((_bb(o)[0][1]+_bb(o)[1][1])/2-y)<.28 for o in lamps):
            continue
        table=_aptd_asset('HSSD_e4bf06896b67fc56bbded3bbd2086ad6dcdb7746',name+'_nightstand'+str(sign),(x,y,lo[2]),(.40,.38,.52))
        _set_big_slot(table,_aptb_wood('aptd_bedside_oak',(.34,.22,.12)))
        _aptd_asset('B0825DKP92',name+'_lamp'+str(sign),(x,y,lo[2]+.523),(.24,.24,.40))
        count+=2
    if not count:
        # Still improve the existing supported pair's greenery without inventing a blocked gap.
        for lamp in lamps:
            aa,bb=_bb(lamp)
            _aptd_green(((aa[0]+bb[0])/2+.12,(aa[1]+bb[1])/2,aa[2]),name+'_green',.20)
            count+=1
    return count


def _aptd_bedding(st,stats):
    result=_aptc_pillows(st,stats)
    # Side hems must clear the frame too; mattress-only rays leave them inside rails.
    for r,lo,hi,cx,cy,ax,hd,length,width,zt in _beds():
        frames=[o for o in bpy.data.objects if o.type=='MESH' and
                (o.name.startswith('BedFactory') or o.name==f'apt_SpareBed({r})') and _in_box(o,lo,hi)]
        if not frames:
            continue
        trees=_surf_trees(frames)
        for kind in ('Duvet','Throw','Fold','Runner'):
            o=bpy.data.objects.get(f'apt_{kind}({r})')
            if o is None:
                continue
            contact=set(o.get('contact_vertices',[]))
            shifted=0
            for v in o.data.vertices:
                if v.index in contact:
                    continue
                axis=1 if ax else 0
                centre=cy if ax else cx
                side=1 if v.co[axis]>=centre else -1
                for step in range(180):
                    z=_surf_z(trees,v.co.x,v.co.y,zt+.20)
                    if z is None or z<v.co.z-.004:
                        break
                    v.co[axis]+=side*.005
                    shifted+=1
                else:
                    raise RuntimeError('Bed rail clearance failed '+r)
            o.data.update()
            o['pkg_h_aptd_rail_clearance']=shifted
        result+=1
    return result


def _aptd_books(shelf,name):
    a,b=_bb(shelf)
    trees=_surf_trees([shelf])
    wide=b[0]-a[0]>b[1]-a[1]
    cx,cy=(a[0]+b[0])/2,(a[1]+b[1])/2
    levels=[]
    ceiling=b[2]-.06
    for i in range(16):
        z=_surf_z(trees,cx,cy,ceiling)
        if z is None or z<a[2]+.08:
            break
        if not levels or abs(z-levels[-1])>.08:
            levels.append(z)
        ceiling=z-.06
    made=0
    for k,z in enumerate(sorted(levels)):
        gap=min([v-z for v in levels if v>z+.08] or [.35])
        span=(b[0]-a[0] if wide else b[1]-a[1])-.10
        depth=(b[1]-a[1] if wide else b[0]-a[0])-.035
        if span<.25 or depth<.12 or gap<.15:
            continue
        for j,offset in enumerate([-.25,.25]):
            x,y=(cx+offset*span,cy) if wide else (cx,cy+offset*span)
            fit=(span*.42,depth*.85,min(.24,gap-.05)) if wide else (depth*.85,span*.42,min(.24,gap-.05))
            o=_book('Books for Wall Shelves|Home Design Interiors Magazine',400+k*2+j,x,y,z+.003,0 if wide else math.pi/2,fit)
            if o is None:
                raise RuntimeError('Book asset unavailable')
            _aptd_fit(o,(x,y,z+.003),fit)
            o.name='aptd_'+name+f'_{k}_{j}'
            made+=1
    if not made:
        raise RuntimeError('No open shelf boards '+shelf.name)
    return made


def _aptd_basin_close():
    r='bathroom_0/2'
    old=_aptd_obj('aptb_'+r+'_open_basin')
    a,b=_bb(old)
    cx,cy=(a[0]+b[0])/2,(a[1]+b[1])/2
    z=b[2]+.014
    # Continuous slab rim and inward bowl; no disconnected oval in a rectangle.
    rings=[(.53,.25,z),(.37,.185,z),(.32,.145,z-.055),(.245,.105,z-.14),(.018,.018,z-.145)]
    verts=[]
    for rx,ry,h in rings:
        for j in range(96):
            t=2*math.pi*j/96
            c,s=math.cos(t),math.sin(t)
            p=.5 if rx>.03 else 1
            verts.append((cx+rx*math.copysign(abs(c)**p,c),cy+ry*math.copysign(abs(s)**p,s),h))
    faces=[]
    for k in range(len(rings)-1):
        for j in range(96):
            a=k*96+j;b=k*96+(j+1)%96
            faces.append((a,b,b+96,a+96))
    me=bpy.data.meshes.new('aptd_ContinuousCeramicBasin');me.from_pydata(verts,[],faces);me.update()
    ob=bpy.data.objects.new('aptd_C_integrated_basin',me);bpy.context.scene.collection.objects.link(ob)
    me.materials.append(_aptc_mat('aptd_porcelain',(.83,.82,.78),.18))
    for p in me.polygons:p.use_smooth=True
    solid=ob.modifiers.new('Ceramic wall thickness','SOLIDIFY');solid.thickness=.012
    _aptb_remove([q for q in bpy.data.objects if q.name.startswith('aptb_'+r+'_basin_rim')]+[old])
    return 1


def _aptd_p7(key,st,stats):
    if key=='p7_01':
        old=_aptd_obj('AboCoffeeFactory(B07HSLKFD5).spawn_asset(39)')
        _aptd_coffee(old,'p7_A_glass',(2.604,7,.1509),True)
        o=_aptd_obj('aptb_aptd_p7_A_glass');a,b=_bb(o)
        glass=_aptb_mat('aptd_coffee_glass',(.92,.96,.95),.04,glass=1)
        o.data.materials.append(glass)
        for p in o.data.polygons:
            if min((o.matrix_world@o.data.vertices[i].co).z for i in p.vertices)>b[2]-.055:
                p.material_index=len(o.data.materials)-1
        return 1
    if key=='p7_02':
        return _aptd_rug(_aptd_obj('apt_LivingRug(living-room_0/0)'),'checker')
    if key=='p7_03':
        return _aptd_soft(_aptd_obj('aptb_A_red_chaise'),'p7_A',(.40,.17,.065))
    if key=='p7_04':
        return _aptd_soft(_aptd_obj('aptb_living-room_0/2_sofa'),'p7_C',(.15,.17,.12))
    if key=='p7_05':
        _aptd_coffee(_aptd_obj('AboCoffeeFactory(B07L8DT2XT).spawn_asset(45)'),'p7_B_cream',(12.25,8.0914,.1509))
        _set_slots(_aptd_obj('aptb_aptd_p7_B_cream'),_aptc_mat('aptd_table_cream',(.77,.73,.62),.4))
        return 1
    if key=='p7_06':
        _set_big_slot(_aptd_obj('AboArmchairFactory(B082QCY5SV).spawn_asset(47)'),_aptd_weave('p7_green_chair',(.12,.18,.085)))
        return 1
    if key=='p7_07':
        return _aptd_rug(_aptd_obj('apt_LivingRug(living-room_0/1)'),'stripe')
    if key=='p7_08':
        return _aptd_books(_aptd_obj('AboBookcaseFactory(B07QW1L8H6).spawn_asset(41)'),'p7_A_books')
    if key=='p7_09':
        return _aptd_books(_aptd_obj('AboBookcaseFactory(B07H8SSBVT).spawn_asset(46)'),'p7_B_books')
    if key=='p7_10':
        table=_aptd_obj('aptb_C_console_shelf.001');a,b=_bb(table)
        _aptd_asset('B0825DKP92','p7_C_console_lamp',(20.4,5.10,b[2]+.003),(.25,.25,.40))
        _aptd_asset('HSSD_23b5b1fc6feeab3f96891017de6dff09d187ae51','p7_C_console_tray',(20.4,5.47,b[2]+.003),(.23,.28,.03))
        return 2
    if key=='p7_11':
        run=_aptd_obj('apt_KitchenRun(kitchen_0/0)');count=0
        for slot in run.material_slots:
            if slot.material and slot.material.name.startswith(('ir_apt_kfront','ir_apt_kpanel')):
                slot.material=_aptb_wood('aptd_p7_oak_kitchen',(.36,.22,.105));count+=1
        return count
    if key=='p7_12':
        table=_aptd_obj('TableDiningFactory(2255916).spawn_asset(36)')
        _set_big_slot(table,_aptb_wood('aptd_p7_dining_oak',(.36,.22,.105)))
        chairs=_aptb_in('kitchen_0/1',('ChairFactory','Real_deskchair','apt_R2Chair','aptb_kitchen_0/1_chair'))
        if not chairs:raise RuntimeError('B dining chairs absent')
        for o in chairs:_set_big_slot(o,_aptd_weave('p7_mustard_chair',(.66,.43,.055)))
        return 1+len(chairs)
    if key=='p7_13':
        return _aptd_bedding(st,stats)
    if key=='p7_14':
        count=0
        for o in bpy.data.objects:
            if o.name.startswith('apt_BathRug('):
                a,b=_bb(o);r=o.name.split('(')[1].split(')')[0];lo,hi,aa,bb=_aptb_room(r)
                o.location.z+=lo[2]+.004-a[2]
                _set_slots(o,_aptd_weave('p7_bathmat',(.49,.40,.28)));count+=1
        return count
    if key=='p7_15':
        return _aptd_basin_close()
    raise KeyError(key)


def _aptd_fresh(aid,name,pos,size,yaw=0):
    import json,abo_assets
    from mathutils import Matrix
    entries=json.load(open('/jarvis/project/robomituba/vendor_datasets/hssd_objects/hssd_object_index.json'))['objects']
    entry=next(e for e in entries if e['id']==aid)
    o=abo_assets._import(entry,'aptd_'+name)
    o.matrix_world=Matrix.Identity(4)
    _ra()._stand(o,*pos,yaw,size,grow=True)
    return _aptd_fit(o,pos,size)


def _aptd_p9_gallery(r):
    lo,hi,a,b=_aptb_room(r)
    x=b[0]-.13;y=a[1]+1.6;z=lo[2]+1.32
    shelf=_aptd_asset('HSSD_27e6430dd4751ae34f91f82e7a33556888d09472','p9_gallery_'+r,(x,y,z),(.22,1.6,.055),math.pi/2)
    for k,aid in enumerate(['HSSD_095f7eda4e8c3ada16329ccff0aed0820d3f6342','HSSD_03db4f1ffb7ef40b11cb080785e9c193c0114f41']):
        o=_picture(aid,0,b[0]-.055,y-.42+k*.82,z+.06,math.pi,.65,.55)
        if o is None:raise RuntimeError('Gallery art unavailable')
        o.name='aptd_p9_gallery_'+r+str(k)
    return 3


def _aptd_p9_screen():
    monitor=_aptd_obj('Real_hssd(HSSD_2029bfb9eca4ab612eb6724916cbff472de47d7b)')
    source=_aptd_fresh('HSSD_b88a1abf821f1b54050d30e82c03ecb461a51918','screen_image_source',(0,0,-10),(.8,.05,.5))
    images=[n.image for slot in source.material_slots if slot.material and slot.material.use_nodes for n in slot.material.node_tree.nodes if n.type=='TEX_IMAGE' and n.image and 'normal' not in n.image.name.lower()]
    if not images:raise RuntimeError('Landscape image unavailable')
    im=max(images,key=lambda v:v.size[0]*v.size[1]);im.pack()
    mat=_aptc_mat('aptd_landscape_screen',(.1,.1,.1),.25);n=mat.node_tree.nodes;l=mat.node_tree.links;bs=n.get('Principled BSDF')
    tc=n.new('ShaderNodeTexCoord');sep=n.new('ShaderNodeSeparateXYZ');vec=n.new('ShaderNodeCombineXYZ');tex=n.new('ShaderNodeTexImage');tex.image=im;tex.extension='EXTEND'
    l.new(tc.outputs['Generated'],sep.inputs[0]);l.new(sep.outputs['X'],vec.inputs['X']);l.new(sep.outputs['Z'],vec.inputs['Y']);l.new(vec.outputs[0],tex.inputs[0]);l.new(tex.outputs['Color'],bs.inputs['Base Color']);l.new(tex.outputs['Color'],bs.inputs['Emission Color']);bs.inputs['Emission Strength'].default_value=.35
    count=0
    for slot in monitor.material_slots:
        if slot.material and slot.material.name=='ir_apt_screen_abstract':slot.material=mat;count+=1
    bpy.data.objects.remove(source,do_unlink=True)
    return count


def _aptd_p9_plantcase():
    old=_aptd_obj('Real_hssd(HSSD_4561530bfb8b3aeacadf64388d82000b2d2e56d1)');a,b=_bb(old)
    new=_aptd_fresh('HSSD_4561530bfb8b3aeacadf64388d82000b2d2e56d1','p9_glazed_plant_case',((a[0]+b[0])/2,(a[1]+b[1])/2,a[2]),tuple(b[i]-a[i] for i in range(3)),math.pi/2)
    glass=_aptb_mat('aptd_case_glass',(.94,.97,.96),.025,glass=1)
    frame=_aptc_mat('aptd_case_black',(.018,.025,.021),.35)
    found=0
    for slot in new.material_slots:
        mat=slot.material
        if not mat or not mat.use_nodes:continue
        bs=next((n for n in mat.node_tree.nodes if n.type=='BSDF_PRINCIPLED'),None)
        if bs and (bs.inputs['Transmission Weight'].default_value>.1 or 'glass' in mat.name.lower()):
            slot.material=glass;found+=1
        else:slot.material=frame
    if not found:
        # The source's broad planar door panes have a separate material index.
        area={}
        for p in new.data.polygons:area[p.material_index]=area.get(p.material_index,0)+p.area
        if len(area)<2:raise RuntimeError('Plant case has no separate glazing')
        index=max(area,key=area.get);new.material_slots[index].material=glass;found=1
    trees=_surf_trees([new]);levels=_shelf_levels(new)
    count=0
    for k,z in enumerate(levels):
        if a[2]+.1<z<b[2]-.25:
            for j,dy in enumerate([-.22,.22]):
                x,y=(a[0]+b[0])/2,(a[1]+b[1])/2+dy
                actual=_surf_z(trees,x,y,z+.035)
                if actual is not None and abs(actual-z)<.06:
                    _aptd_green((x,y,actual+.003),'p9_case_plant'+str(k)+'_'+str(j),.22);count+=1
    if not count:raise RuntimeError('Plant case shelf support missing')
    bpy.data.objects.remove(old,do_unlink=True)
    return found+count


def _aptd_warm_floor():
    import numpy as np
    from PIL import Image
    mat=_aptc_mat('aptd_p9_scanned_oak',(.32,.22,.13),.52)
    if mat.get('aptd_scan'):
        return mat
    scan=PBR_STRUCT+'wood_planks_grey'
    path=scan+'/base_color.jpg'
    rgb=np.asarray(Image.open(path).convert('RGB').resize((512,512)),dtype=np.float64)/255
    linear=np.where(rgb<=.04045,rgb/12.92,((rgb+.055)/1.055)**2.4)
    _PBR_MEAN[path]=float((linear@np.array([.2126,.7152,.0722])).mean())
    if not _pbr_build(mat,scan,(.32,.22,.13),tile=1.5,contrast=.55,rough=.52,normal=.7,var=.03,ao=.12):
        raise RuntimeError('Scanned oak maps missing')
    mat['aptd_scan']=scan
    return mat


def _aptd_craft_shade(old):
    from mathutils import Matrix
    a,b=_bb(old);cx,cy=(a[0]+b[0])/2,(a[1]+b[1])/2
    shade=_aptd_asset('PH_wicker_basket_02','p9_woven_basket_shade',(cx,cy,1.70),(.55,.45,.30))
    aa,bb=_bb(shade);centre=Vector((cx,cy,(aa[2]+bb[2])/2))
    shade.matrix_world=Matrix.Translation(centre)@Matrix.Rotation(math.pi,4,'X')@Matrix.Translation(-centre)@shade.matrix_world
    ceiling=_zc('office_0/0',_rooms()['office_0/0'][0]);top=_bb(shade)[1][2]
    bpy.ops.mesh.primitive_cylinder_add(vertices=16,radius=.003,depth=ceiling-top,location=(cx,cy,(top+ceiling)/2))
    cord=bpy.context.object;cord.name='aptd_p9_craft_cord';cord.data.materials.append(_aptc_mat('aptd_black_cord',(.02,.02,.02),.6))
    _globe('aptd_p9_craft_bulb',cx,cy,1.85,_emit('aptd_craft_bulb',(1,.8,.55),2),r=.023)
    bpy.data.objects.remove(old,do_unlink=True)
    return 3


def _aptd_p9(key,st,stats):
    if key=='p9_01':
        count=0
        for r,(lo,hi,t) in _rooms().items():
            if t in ('bedroom','living-room','kitchen','office'):
                _set_slots(_aptd_obj(r+'.floor'),_aptd_warm_floor());count+=1
        return count
    if key=='p9_02':
        objects=[o for o in bpy.data.objects if o.type=='MESH' and o.name.startswith(('apt_Wardrobe(','OakWardrobeFactory'))]
        for o in objects:_set_big_slot(o,_aptb_wood('aptd_p9_wardrobe_oak',(.38,.24,.12)))
        return len(objects)
    if key=='p9_03':return _aptd_bedding(st,stats)
    if key=='p9_04':
        rug=_aptd_asset('HSSD_17b51b1db09e0075356d6e7613ef0e16ab4e215d','p9_A_woven_rug',(2.15,6.45,.139),(3.2,2.1,.018))
        return 1
    if key=='p9_05':
        return _aptd_soft(_aptd_obj('Real_loungesofa(B07B4MF2MF)'),'p9_A',(.38,.29,.18))
    if key=='p9_06':
        shelves=_aptb_in('living-room_0/1',('Real_bookcase',))
        if not shelves:raise RuntimeError('Library cases missing')
        count=0
        for k,o in enumerate(shelves):
            _set_big_slot(o,_aptc_mat('aptd_library_black',(.02,.025,.022),.5))
            count+=_aptd_books(o,'p9_library'+str(k))
            a,b=_bb(o)
            ceiling=_zc('living-room_0/1',_rooms()['living-room_0/1'][0])
            levels=[z for z in _shelf_levels(o) if a[2]+.10<z<ceiling-.25]
            if not levels:raise RuntimeError('Library plant shelf missing')
            z=max(levels)
            # Keep greenery inside the cabinet height and leave it its own shelf bay.
            for q in list(bpy.data.objects):
                if q.name.startswith('aptd_p9_library'+str(k)+'_') and _bb(q)[0][2]>z-.03:
                    bpy.data.objects.remove(q,do_unlink=True)
            _aptd_green(((a[0]+b[0])/2,(a[1]+b[1])/2,z+.003),'p9_library_green'+str(k),.20)
        return count
    if key=='p9_07':
        return _aptd_soft(_aptd_obj('Real_loungesofa(B07HZ6LVGP)'),'p9_B',(.45,.41,.34))
    if key=='p9_08':
        lo,hi,a,b=_aptb_room('living-room_0/1')
        _aptd_asset('HSSD_103c93c01b6e92d1fb64a488fbe457d3791381e4','p9_B_lower_rug',(16.65,6,lo[2]+.003),(2.8,2.5,.018))
        upper=_aptd_asset('HSSD_21be3b47c82a23b562efe88c5119cc2cceb5ec48','p9_B_upper_rug',(16.6,6,lo[2]+.025),(2.15,1.45,.018))
        return 2
    if key=='p9_09':return _aptd_p9_gallery('kitchen_0/0')+_aptd_p9_gallery('kitchen_0/1')
    if key=='p9_10':
        old=_aptd_obj('Real_hssd(HSSD_21a820e6062536552940bca6c97791bf6445548f).001');a,b=_bb(old)
        return _aptd_craft_shade(old)
    if key=='p9_11':
        _aptd_asset('HSSD_3ec1423e301fa0a5df85fda5875b15dd944d54b4','p9_craft_tool_panel',(1.4,8.22,1.45),(.85,.055,.42))
        _aptd_asset('HSSD_13f59be6cd2d0f811fdfcafb794bde1a513ecbde','p9_craft_basket',(3.65,10.5,.1381),(.4,.3,.30))
        shelves=_aptb_in('office_0/0',('AboBookcaseFactory',))
        count=2
        for k,o in enumerate(shelves):count+=_aptd_books(o,'p9_craft_books'+str(k))
        return count
    if key=='p9_12':
        _aptd_asset('HSSD_17b51b1db09e0075356d6e7613ef0e16ab4e215d','p9_study_woven_rug',(10.7,12.35,.139),(2.6,1.9,.018))
        return 1
    if key=='p9_13':return _aptd_p9_plantcase()
    if key=='p9_14':return _aptd_p9_screen()
    if key=='p9_15':
        old=_aptd_obj('Real_hssd(HSSD_349b4b83f12affe0526e2c5a7148399cb2e40cdd)');a,b=_bb(old)
        _aptd_fresh('HSSD_8fbf3308a956bcaf0e8a195d39d534838ca6fd11','p9_sculptural_linear_pendant',((a[0]+b[0])/2,(a[1]+b[1])/2,1.72),(1.5,.35,.70))
        bpy.data.objects.remove(old,do_unlink=True);return 1
    raise KeyError(key)


def _aptd_feature(key,st,stats):
    if key.startswith('p9_'):
        return _aptd_p9(key,st,stats)
    if key.startswith('p7_'):
        return _aptd_p7(key,st,stats)
    if key=='p8_01':
        o=_aptd_obj('aptb_aptc_A_sideboard')
        _set_big_slot(o,_aptb_wood('aptd_A_walnut',(.20,.105,.045)))
        return 1
    if key=='p8_02':
        o=_aptd_obj('AboArmchairFactory(B07J2VY555).spawn_asset(35)')
        _aptd_move(o,4.65,7.15,.1438,-math.pi/2)
        a,b=_bb(o)
        assert a[1]>6.7142 and b[1]<7.8552 and a[0]>3.75
        return 1
    if key=='p8_03':
        return _aptd_coffee(_aptd_obj('AboCoffeeFactory(B07K7LZT5Z).spawn_asset(32)'),'A_coffee',(2.817,5.9998,.1438))
    if key=='p8_04':
        o=_aptd_obj('aptb_living-room_0/0_sofa')
        _set_big_slot(o,_aptd_weave('A_charcoal',(.055,.065,.075)))
        return 1+_aptd_soft(o,'p8_A',(.48,.43,.34))
    if key=='p8_05':
        return _aptd_rug(_aptd_obj('apt_LivRug(living-room_0/0)'))
    if key=='p8_06':
        count=0
        for mat in bpy.data.materials:
            if mat.name not in ['aptb_aptc_botanical_wall','aptb_aptc_botanical_cloth','aptc_bath_dry_toile']:
                continue
            for n in mat.node_tree.nodes:
                if n.type=='VECT_MATH' and n.operation=='SCALE':
                    n.inputs['Scale'].default_value=1/.18
                    count+=1
        return count
    if key=='p8_07':
        return _aptd_rug(_aptd_obj('apt_LivRug(living-room_0/1)'),'navy_border')
    if key=='p8_08':
        for k,x in enumerate([13.9,14.9]):
            old=_aptd_obj('aptb_aptc_B_lamp'+str(k))
            _aptd_asset('HSSD_16ed94e42536cb7cdeeaa42095eaad1950dfb811','B_shaded_lamp'+str(k),(x,4.43,.9858),(.30,.30,.48))
            bpy.data.objects.remove(old,do_unlink=True)
        return 2
    if key=='p8_09':
        old=_aptd_obj('Real_loungesofa(B07B4MF2MF)')
        new=_aptd_asset('HSSD_8d4442ba5d31ebcbd6e33efad5c3531b6583ef32','B_slipcover',(15.7715,6.4998,.1438),(.90,2.10,.92),-math.pi/2)
        _set_big_slot(new,_aptd_weave('B_linen',(.76,.73,.65)))
        result=_aptd_soft(new,'p8_B',(.24,.32,.43))
        bpy.data.objects.remove(old,do_unlink=True)
        return 1+result
    if key=='p8_10':
        return _aptd_tableware(_aptd_obj('aptb_kitchen_0/0_dining'),'A_dining')
    if key=='p8_11':
        table=_aptd_obj('aptb_kitchen_0/1_dining')
        result=_aptd_tableware(table,'B_festive')
        _aptd_asset('HSSD_87ac831ae9463acf6ee6a876de63ed07561aef03','B_kitchen_tree',(23.1,4.9,.1438),(.70,.70,1.55))
        return result+1
    if key=='p8_12':
        from mathutils import Matrix
        count=0
        for r in ['kitchen_0/0','kitchen_0/1']:
            board=next((o for o in bpy.data.objects if o.name=='aptb_aptc_'+r+'board'),None)
            if board is None:
                board=next((o for o in bpy.data.objects if o.name=='aptb_'+r+'_board'),None)
            lo,hi,a,b=_aptb_room(r)
            run=_aptd_obj('apt_KitchenRun('+r+')')
            z=_surf_z(_surf_trees([run]),a[0]+1.60,b[1]-.35,lo[2]+1.2)
            if z is None:
                raise RuntimeError('Counter ray missing')
            if board:
                _aptd_fit(board,(a[0]+1.6,b[1]-.35,z+.003),(.24,.035,.30))
                count+=1
            _aptd_green((a[0]+.85,b[1]-.34,z+.003),'counter_'+r,.32)
            count+=1
        return count
    if key=='p8_13':
        result=_aptd_bedding(st,stats)
        for o in bpy.data.objects:
            if o.name.startswith('apt_Throw('):
                _set_slots(o,_aptd_weave('knit_'+o.name,(.15,.21,.30) if _bb(o)[0][0]>12 else (.13,.14,.15)))
        return result
    if key=='p8_14':
        return _aptd_bedpair('bedroom_0/1','A_small')
    if key=='p8_15':
        return _aptd_bedpair('bedroom_0/3','B_small')
    raise KeyError(key)


def _aptd_apply(st,stats):
    style=next((k for k,v in STYLES.items() if v is st),None)
    done=set(str(bpy.context.scene.get('pkg_h_aptd_done','')).split(','))
    for key in _APTD_ENABLED:
        if not key.startswith(str(style)+'_') or key in done:
            continue
        try:
            result=_aptd_feature(key,st,stats)
            if not result:
                raise RuntimeError('No effective changes '+key)
            done.add(key)
            bpy.context.scene['pkg_h_aptd_done']=','.join(sorted(done))
            stats['pkg_h_aptd_'+key]=result
        except Exception as ex:
            import traceback
            traceback.print_exc()
            stats['pkg_h_aptd_'+key+'_error']=repr(ex)
