"""Simple procedural warehouse assets the realizer can spawn (factory-shaped like Infinigen's: Cls(seed).spawn_asset(i)).

Cardboard boxes (one size per seed, per-box brown via Object Info random), wooden pallets (EUR 1.2 x 0.8 m: top boards, blocks,
bottom boards) and box piles (a few boxes stacked on a pallet footprint). Materials are plain Principled BSDFs, so the GT AOVs
(albedo / roughness / metallic) read straight from their inputs.
"""
from __future__ import annotations

import math
import os
import random
import zlib
from pathlib import Path

import bpy


def _material(name, colors, rough):
    m = bpy.data.materials.get(name)
    if m is not None:
        return m
    m = bpy.data.materials.new(name); m.use_nodes = True
    nt = m.node_tree; b = nt.nodes["Principled BSDF"]
    info = nt.nodes.new("ShaderNodeObjectInfo"); ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].color = (*colors[0], 1); ramp.color_ramp.elements[1].color = (*colors[1], 1)
    nt.links.new(info.outputs["Random"], ramp.inputs["Fac"]); nt.links.new(ramp.outputs["Color"], b.inputs["Base Color"])
    b.inputs["Roughness"].default_value = rough
    if SURFACE_DETAIL and (k_ := _scan_kind(name, 0.0, False)):
        _scan(m, colors[1], rough, k_, name)
    return m


def cardboard(tone=None):
    """Kraft cardboard; `tone` 0-3 picks a shade (pale, standard, dark, white mailer) -- one tan for every box read as 'stamped out'
    (warehouse r17)."""
    shades = (((0.36, 0.22, 0.11), (0.52, 0.36, 0.2)), ((0.48, 0.34, 0.2), (0.62, 0.48, 0.32)), ((0.26, 0.15, 0.07), (0.38, 0.24, 0.12)),
              ((0.78, 0.77, 0.74), (0.88, 0.87, 0.84)))
    t = random.randrange(4) if tone is None else tone % 4
    return _material(f"ir_cardboard_{t}" if t else "ir_cardboard", shades[t], 0.85)


def pallet_wood():
    return _material("ir_pallet_wood", ((0.45, 0.33, 0.2), (0.62, 0.5, 0.34)), 0.8)


def _face_uvs(bm, verts):
    """Give every face of the boxes made from `verts` its own full 0..1 UV square, upright as seen from outside: bmesh's cube UVs share
    one atlas, so a printed image showed rotated and zoomed to a corner of the board (whiteboard / screen test, 2026-10-17).
    Call after the box is scaled and before it is rotated."""
    uv = bm.loops.layers.uv.verify()
    table = {(0, 1): (1, 1, 2), (0, -1): (1, -1, 2), (1, 1): (0, -1, 2), (1, -1): (0, 1, 2), (2, 1): (0, 1, 1), (2, -1): (0, 1, 1)}
    for f in {f for v in verts for f in v.link_faces}:
        f.normal_update(); n = f.normal; ax = max(range(3), key=lambda k: abs(n[k])); u_ax, u_s, v_ax = table[(ax, 1 if n[ax] > 0 else -1)]
        us = [u_s * l.vert.co[u_ax] for l in f.loops]; vs = [l.vert.co[v_ax] for l in f.loops]
        u0, u1, v0, v1 = min(us), max(us), min(vs), max(vs)
        for l, u, v in zip(f.loops, us, vs):
            l[uv].uv = ((u - u0) / max(u1 - u0, 1e-9), (v - v0) / max(v1 - v0, 1e-9))


def _boxes(name, parts, mat):
    """One mesh object from axis-aligned boxes [(cx, cy, cz, sx, sy, sz)], origin at the bottom centre."""
    import bmesh
    bm = bmesh.new(); bm.loops.layers.uv.verify()
    for cx, cy, cz, sx, sy, sz in parts:
        r = bmesh.ops.create_cube(bm, size=1.0, calc_uvs=True)
        bmesh.ops.scale(bm, vec=(sx, sy, sz), verts=r["verts"])
        _face_uvs(bm, r["verts"])
        bmesh.ops.translate(bm, vec=(cx, cy, cz), verts=r["verts"])
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    me.materials.append(mat)
    o = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(o)
    _bevel(o)
    return o


class CardboardBoxFactory:
    def __init__(self, seed):
        r = random.Random(seed); self.r = r
        self.size = (r.uniform(0.25, 0.6), r.uniform(0.2, 0.45), r.uniform(0.15, 0.4))

    def spawn_asset(self, i):
        """A carton (front +X) with its packing tape over the lid and down the front, and a shipping label with a barcode: plain kraft
        cubes were 'toy blocks, no tape, no label' in every warehouse round (floor J r27-r29, 3 of 3; user 2026-10-17)."""
        x, y, z = self.size; r = self.r
        groups = [(cardboard(), [(0, 0, z / 2, x, y, z)])]
        if r.random() < 0.85:
            tape = _flat("ir_pack_tape", (0.66, 0.52, 0.3), 0.3)
            groups.append((tape, [(0, 0, z + 0.0015, x + 0.004, 0.05, 0.004), (x / 2 + 0.0015, 0, z * 0.85, 0.004, 0.05, z * 0.3)]))
        if r.random() < 0.6:
            ly = r.uniform(-0.25, 0.25) * y
            lw, lh = min(0.13, y * 0.5), min(0.09, z * 0.45)
            groups.append((_flat("ir_ship_label", (0.95, 0.95, 0.92), 0.6), [(x / 2 + 0.0015, ly, z * 0.42, 0.004, lw, lh)]))
            groups.append((_flat("ir_barcode", (0.03, 0.03, 0.03), 0.5), [(x / 2 + 0.0035, ly, z * 0.42 - lh * 0.2, 0.004, lw * 0.7, lh * 0.28),
                                                                         (x / 2 + 0.0035, ly - lw * 0.2, z * 0.42 + lh * 0.3, 0.004, lw * 0.4, lh * 0.12)]))
        o = _parts_object(f"CardboardBoxFactory({i}).spawn_asset({i})", groups)
        o.modifiers.new("bevel", "BEVEL").width = 0.006
        return o


class BagFactory:
    """A bag left by its owner (front +X): a backpack (rounded body, front pocket, top handle) or a tote with two handles -- signs of
    use the critics kept asking for (floors D3/E3/F3 r10-r12: 'no bags, nothing left around', use 4-6 in every room)."""
    def __init__(self, seed):
        r = random.Random(seed); self.r = r; self.kind = "backpack"   # no tote: a beige tote read as 'a sack-like blob' (floor D3 r14, 2/3)
        self.c = r.choice(((0.08, 0.1, 0.16), (0.28, 0.28, 0.3), (0.12, 0.25, 0.18), (0.05, 0.05, 0.05)))   # no red: by a desk it read
        # as 'a fire extinguisher lying on the floor' (floor J r19, 3 of 3)

    def spawn_asset(self, i):
        fab = _flat(f"ir_bag_{int(self.c[0] * 100)}_{int(self.c[2] * 100)}", self.c, 0.8)
        if self.kind == "backpack":
            return _prims(f"BagFactory({i}).spawn_asset({i})", [(fab, [("rbox", (0, 0, 0.21), (0.2, 0.3, 0.42), (0, -0.15, 0)),
                                                                      ("rbox", (0.11, 0, 0.13), (0.06, 0.22, 0.18), (0, -0.15, 0)),
                                                                      ("cyl", (-0.04, 0, 0.44), (0.015, 0.015, 0.08), (math.pi / 2, 0, 0))])])
        return _prims(f"BagFactory({i}).spawn_asset({i})", [(fab, [("rbox", (0, 0, 0.17), (0.12, 0.4, 0.34), (0, 0, 0)),
                                                                  ("box", (0, 0.1, 0.4), (0.01, 0.02, 0.14), (0, 0, 0)), ("box", (0, -0.1, 0.4), (0.01, 0.02, 0.14), (0, 0, 0))])])


class ExerciseMatFactory:
    """A gym floor mat (front +X): a 1.8 x 0.6 m pad, 1.5 cm thick, sometimes with a ball or a foam roller on it."""
    def __init__(self, seed):
        r = random.Random(seed); self.r = r
        self.c = r.choice(((0.15, 0.3, 0.55), (0.1, 0.45, 0.4), (0.55, 0.15, 0.2), (0.25, 0.25, 0.28)))

    def spawn_asset(self, i):
        r = self.r
        mat = _flat(f"ir_gym_mat_{int(self.c[2] * 100)}", self.c, 0.85)
        prop = _flat(f"ir_gym_prop_{r.randrange(3)}", r.choice(((0.9, 0.5, 0.1), (0.2, 0.6, 0.8), (0.7, 0.7, 0.72))), 0.6)
        extra = r.choice((
            [("sph", (0.1, 0.45, 0.33), (0.32, 0.32, 0.32), (0, 0, 0))],                         # a gym ball at the end
            [("cyl", (0.0, 0.6, 0.09), (0.075, 0.075, 0.45), (math.pi / 2, 0, 0))],              # a foam roller
            []))
        return _prims(f"ExerciseMatFactory({i}).spawn_asset({i})", [(mat, [("rbox", (0, 0, 0.0075), (0.6, 1.8, 0.015), (0, 0, 0))])] +
                      ([(prop, extra)] if extra else []))


class DryGoodsFactory:
    """Back-stockroom stock that is not a carton: a printed paper sack (flour, sugar, coffee beans), a row of tins, or a shrink-wrapped
    case of bottles (floors G/H/I r12-r14: 'generic cartons and bins, nothing says café dry goods', 3 of 3 each)."""
    def __init__(self, seed):
        r = random.Random(seed); self.r = r; self.kind = r.choice(("sack", "sack", "tins", "bottles"))

    def spawn_asset(self, i):
        r, k = self.r, self.kind
        if k == "sack":
            paper = _flat(f"ir_sack_{r.randrange(3)}", r.choice(((0.78, 0.7, 0.55), (0.85, 0.82, 0.75), (0.45, 0.32, 0.2))), 0.85)
            band = _flat(f"ir_sack_print_{r.randrange(3)}", r.choice(((0.6, 0.12, 0.08), (0.1, 0.3, 0.55), (0.15, 0.4, 0.2))), 0.6)
            return _prims(f"DryGoodsFactory({i}).spawn_asset({i})", [(paper, [("rbox", (0, 0, 0.12), (0.3, 0.42, 0.24), (0, 0, 0))]),
                                                                    (band, [("box", (0.151, 0, 0.13), (0.004, 0.24, 0.1), (0, 0, 0))])])
        if k == "tins":
            tin = _flat("ir_tin", (0.72, 0.72, 0.74), 0.3, 0.9); lab = _flat(f"ir_tin_label_{r.randrange(3)}", r.choice(((0.75, 0.15, 0.1), (0.95, 0.75, 0.15), (0.2, 0.45, 0.25))), 0.5)
            parts_t = [("cyl", (0, -0.15 + j * 0.1, 0.06), (0.042, 0.042, 0.12), (0, 0, 0)) for j in range(4)]
            parts_l = [("cyl", (0, -0.15 + j * 0.1, 0.06), (0.043, 0.043, 0.07), (0, 0, 0)) for j in range(4)]
            return _prims(f"DryGoodsFactory({i}).spawn_asset({i})", [(tin, parts_t), (lab, parts_l)])
        glass = _flat(f"ir_syrup_{r.randrange(3)}", r.choice(((0.5, 0.25, 0.08), (0.65, 0.1, 0.12), (0.3, 0.18, 0.1))), 0.1, transmission=0.6)
        wrap = _flat("ir_shrinkwrap", (0.9, 0.9, 0.92), 0.2, transmission=0.5)
        parts_b = [("cyl", (sx * 0.06, -0.12 + j * 0.08, 0.13), (0.03, 0.03, 0.26), (0, 0, 0)) for sx in (1, -1) for j in range(4)]
        return _prims(f"DryGoodsFactory({i}).spawn_asset({i})", [(glass, parts_b), (wrap, [("box", (0, 0, 0.02), (0.26, 0.36, 0.04), (0, 0, 0))])])


class CafeStockFactory:
    """A café's own back stock: a stack of milk crates with bottles, a carton of sleeved takeaway-cup tubes, or a sack of coffee beans
    with a valve and a printed band (floor G r28: 'generic coloured boxes, nothing says café stockroom', completeness 6, 3 of 3)."""
    def __init__(self, seed):
        r = random.Random(seed); self.r = r; self.kind = r.choice(("crates", "cups", "beans", "beans"))

    def spawn_asset(self, i):
        r, k = self.r, self.kind
        if k == "crates":
            pl = _flat(f"ir_crate_{r.randrange(3)}", r.choice(((0.6, 0.08, 0.06), (0.08, 0.22, 0.5), (0.12, 0.38, 0.18))), 0.5)
            milk = _flat("ir_milk", (0.93, 0.93, 0.9), 0.3); cap = _flat("ir_milk_cap", (0.1, 0.35, 0.75), 0.4)
            n = r.randint(1, 2); c, b, cp = [], [], []   # <= 2 high: three (0.87 m) fitted no shelf level (G r33-r34)
            for j in range(n):
                z = j * 0.29
                c += [("box", (0, 0, z + 0.01), (0.36, 0.36, 0.02), (0, 0, 0))] + \
                     [("box", (sx * 0.17, 0, z + 0.14), (0.02, 0.36, 0.28), (0, 0, 0)) for sx in (1, -1)] + \
                     [("box", (0, sy * 0.17, z + 0.14), (0.36, 0.02, 0.28), (0, 0, 0)) for sy in (1, -1)]
            zt = (n - 1) * 0.29
            for bx in (-0.08, 0.08):
                for by in (-0.08, 0.08):
                    b.append(("cyl", (bx, by, zt + 0.15), (0.05, 0.05, 0.26), (0, 0, 0)))
                    cp.append(("cyl", (bx, by, zt + 0.29), (0.022, 0.022, 0.025), (0, 0, 0)))
            return _prims(f"CafeStockFactory({i}).spawn_asset({i})", [(pl, c), (milk, b), (cap, cp)])
        if k == "cups":
            card = _flat("ir_carton", (0.62, 0.46, 0.28), 0.85); cup = _flat("ir_cup_paper", (0.95, 0.94, 0.9), 0.5)
            sl = _flat("ir_cup_sleeve", (0.85, 0.87, 0.9), 0.15, transmission=0.4)
            tubes = [("cyl", (0.05, -0.15 + j * 0.1, 0.28), (0.045, 0.045, 0.3), (0, 0, 0)) for j in range(4)]
            return _prims(f"CafeStockFactory({i}).spawn_asset({i})", [(card, [("box", (0, 0, 0.11), (0.3, 0.44, 0.22), (0, 0, 0))]),
                                                                      (cup, tubes), (sl, [("box", (0.05, 0, 0.42), (0.1, 0.42, 0.01), (0, 0, 0))])])
        kraft = _flat("ir_bean_bag", (0.45, 0.3, 0.18), 0.75); blk = _flat("ir_ink", (0.05, 0.05, 0.06), 0.6)
        band = _flat(f"ir_bean_band_{r.randrange(3)}", r.choice(((0.85, 0.75, 0.55), (0.7, 0.15, 0.1), (0.15, 0.3, 0.2))), 0.6)
        bags = [("box", (0, y, 0.15), (0.12, 0.17, 0.3), (0, 0, 0)) for y in (-0.1, 0.1)] + \
               [("box", (0, y, 0.315), (0.04, 0.17, 0.03), (0, 0, 0)) for y in (-0.1, 0.1)]   # flat-bottom bags with a folded top, two
        # side by side: one bevelled box read as 'soft beige blobs, pillows' (floor G r35)
        labels = [("box", (0.061, y, 0.14), (0.004, 0.13, 0.12), (0, 0, 0)) for y in (-0.1, 0.1)]
        valves = [("cyl", (0.062, y, 0.24), (0.016, 0.016, 0.004), (0, math.pi / 2, 0)) for y in (-0.1, 0.1)]
        return _prims(f"CafeStockFactory({i}).spawn_asset({i})", [(kraft, bags), (band, labels), (blk, valves)])


class PalletFactory:
    def __init__(self, seed):
        self.seed = seed

    def spawn_asset(self, i):
        L, W, h_top, h_blk, h_bot = 1.2, 0.8, 0.022, 0.078, 0.022
        parts = []
        for k in range(5):                                       # top boards across the length
            parts.append((0, -W / 2 + 0.05 + k * (W - 0.1) / 4, h_bot + h_blk + h_top / 2, L, 0.1, h_top))
        for xi in (-1, 0, 1):
            for yi in (-1, 0, 1):
                parts.append((xi * (L / 2 - 0.07), yi * (W / 2 - 0.07), h_bot + h_blk / 2, 0.14, 0.14, h_blk))
        for yi in (-1, 0, 1):                                    # bottom boards
            parts.append((0, yi * (W / 2 - 0.07), h_bot / 2, L, 0.14, h_bot))
        r, load, z = random.Random(self.seed), [], h_bot + h_blk + h_top
        if r.random() < 0.95:                                    # most pallets carry goods (wh r12: bare ones read as floor slabs) (warehouse r2: 'pallets lie bare')
            for layer in range(r.randint(1, 4)):
                h = r.uniform(0.25, 0.4); nx = r.choice((2, 3))
                for a in range(nx):
                    for b in range(2):
                        if layer and r.random() < 0.2:
                            continue
                        load.append((-L / 2 + (a + 0.5) * L / nx + r.uniform(-0.01, 0.01), -W / 2 + (b + 0.5) * W / 2 + r.uniform(-0.01, 0.01),
                                     z + h / 2, L / nx - 0.02, W / 2 - 0.02, h))
                z += h
        return _parts_object(f"PalletFactory({self.seed}).spawn_asset({i})", [(pallet_wood(), parts)] + ([(cardboard(), load)] if load else []))


class WorkbenchFactory:
    """Packing / work bench (front +X): steel frame, butcher-block or ply top at 0.9 m, a lower shelf, a pegboard upstand at the back,
    a tape gun and a stretch-film roll (warehouse r2: 'dark-topped tables on thin white legs read as an office or dining room')."""
    def __init__(self, seed):
        r = random.Random(seed); self.r = r
        self.L = r.choice((1.5, 1.8, 2.0)); self.frame = r.choice(((0.15, 0.3, 0.55), (0.35, 0.37, 0.4), (0.12, 0.12, 0.12)))

    def spawn_asset(self, i):
        L, D, H = self.L, 0.75, 0.9
        frame = _flat(f"ir_bench_frame_{int(self.frame[2] * 100)}", self.frame, 0.45, 0.6); top = _flat("ir_butcher", (0.6, 0.42, 0.26), 0.55, wood=True)
        peg = _flat("ir_pegboard", (0.62, 0.5, 0.36), 0.7); film = _flat("ir_film", (0.85, 0.9, 0.92), 0.1, transmission=0.6)
        red = _flat("ir_tapegun", (0.75, 0.12, 0.08), 0.4)
        legs = [("box", (sx * (D / 2 - 0.03), sy * (L / 2 - 0.03), H / 2 - 0.02), (0.05, 0.05, H - 0.04), (0, 0, 0)) for sx in (1, -1) for sy in (1, -1)]
        rails = [("box", (0, 0, 0.15), (D - 0.04, L - 0.04, 0.03), (0, 0, 0))]   # no top rail: benches in a row read as one 4 m rod (wh r16)
        rails += [("box", (-D / 2 + 0.03, sy * (L / 2 - 0.03), H + 0.2), (0.04, 0.04, 0.6), (0, 0, 0)) for sy in (1, -1)]
        return _prims(f"WorkbenchFactory({i}).spawn_asset({i})",
                      [(frame, legs + rails), (top, [("box", (0, 0, H - 0.02), (D, L, 0.04), (0, 0, 0)), ("box", (0, 0, 0.175), (D - 0.06, L - 0.06, 0.02), (0, 0, 0))]),
                       (peg, [("box", (-D / 2 + 0.15, 0, H + 0.42), (0.28, L - 0.06, 0.02), (0, 0, 0))]),   # an open shelf, not a panel
                                                                                                         # (wh r12: 'modesty panels -- office desks')
                       (film, [("cyl", (0.1, L / 2 - 0.35, 0.33), (0.07, 0.07, 0.4), (math.pi / 2, 0, 0))]),
                       (red, [("box", (0.15, -L / 2 + 0.3, H + 0.05), (0.06, 0.18, 0.1), (0, 0, 0.4))])])


class ShopStoolFactory:
    """Industrial shop stool: a square steel seat on four straight legs with low stretchers, 0.68 m (warehouse r13-r17: the round black
    stool with a foot ring read as 'a side table or plant stand')."""
    def __init__(self, seed):
        self.c = random.Random(seed).choice(((0.35, 0.37, 0.4), (0.15, 0.25, 0.45), (0.12, 0.12, 0.12)))

    def spawn_asset(self, i):
        steel = _flat(f"ir_shopstool_{int(self.c[2] * 100)}", self.c, 0.45, 0.7)
        legs = [("box", (sx * 0.15, sy * 0.15, 0.33), (0.03, 0.03, 0.66), (0, 0, 0)) for sx in (1, -1) for sy in (1, -1)]
        bars = [("box", (0, sy * 0.15, 0.22), (0.3, 0.02, 0.02), (0, 0, 0)) for sy in (1, -1)] + [("box", (sx * 0.15, 0, 0.22), (0.02, 0.3, 0.02), (0, 0, 0)) for sx in (1, -1)]
        return _prims(f"ShopStoolFactory({i}).spawn_asset({i})", [(steel, legs + bars + [("box", (0, 0, 0.675), (0.36, 0.36, 0.03), (0, 0, 0))])])


class PlatformCartFactory:
    """Flatbed warehouse trolley: a 0.9 x 0.6 deck on four castors, a U handle at one end, sometimes a box or two on it."""
    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        r = self.r
        deck = _flat("ir_cart_deck", r.choice(((0.15, 0.3, 0.6), (0.2, 0.2, 0.22), (0.7, 0.15, 0.1))), 0.5, 0.3)
        steel = _flat("ir_chrome", (0.8, 0.8, 0.82), 0.15, 1.0); rub = _flat("ir_black_metal", (0.03, 0.03, 0.03), 0.4, 1.0)
        wheels = [("cyl", (sx * 0.38, sy * 0.24, 0.05), (0.05, 0.05, 0.03), (math.pi / 2, 0, 0)) for sx in (1, -1) for sy in (1, -1)]
        handle = [("cyl", (-0.44, sy * 0.25, 0.55), (0.012, 0.012, 0.8), (0, 0, 0)) for sy in (1, -1)] + \
                 [("cyl", (-0.44, 0, 0.95), (0.012, 0.012, 0.5), (math.pi / 2, 0, 0))]
        groups = [(deck, [("box", (0, 0, 0.14), (0.9, 0.6, 0.04), (0, 0, 0))]), (steel, handle), (rub, wheels)]
        if r.random() < 0.6:
            groups.append((cardboard(), [("box", (0.1, 0, 0.16 + 0.15), (0.5, 0.4, 0.3), (0, 0, r.uniform(-0.2, 0.2)))]))
        return _prims(f"PlatformCartFactory({i}).spawn_asset({i})", groups)


class BoxPileFactory:
    """1-3 layers of cardboard boxes on a 1.2 x 0.8 m footprint, slightly irregular: goods waiting to be shelved."""
    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        r, parts = self.r, []
        z = 0.0
        for layer in range(r.randint(1, 3)):
            h = r.uniform(0.25, 0.4)
            nx, ny = r.choice((2, 3)), 2
            for a in range(nx):
                for b in range(ny):
                    if layer and r.random() < 0.25:
                        continue                                 # a gap where a box was taken
                    sx, sy = 1.2 / nx - 0.02, 0.8 / ny - 0.02
                    parts.append((-0.6 + (a + 0.5) * 1.2 / nx + r.uniform(-0.01, 0.01), -0.4 + (b + 0.5) * 0.4 + r.uniform(-0.01, 0.01),
                                  z + h / 2, sx, sy, h))
            z += h
        o = _boxes(f"BoxPileFactory({i}).spawn_asset({i})", parts, cardboard())
        o.modifiers.new("bevel", "BEVEL").width = 0.006
        return o


# ---- cafe ---------------------------------------------------------------------------------------------------------------------------
# painted / powder-coated metal is a dielectric under a paint layer: metallic 0 (review 2026-10-17: ceiling T-bar, door frames, cabinets,
# lockers, rack beams, chair bases carried metallic=1 in the ground-truth channel). Bare metals (chrome, steel, aluminium, brass) stay 1.
PAINTED_METAL = ("ir_arch_black_metal", "ir_arch_duct", "ir_black_metal", "ir_desk_frame", "ir_filer", "ir_office_door_frame", "ir_linear_body",
                 "ir_pedestal", "ir_pencup", "ir_phone_body", "ir_microwave_body", "ir_espresso_side", "ir_hanger", "ir_cart", "ir_rack", "ir_locker")


def _flat(name, rgb, rough, metallic=0.0, transmission=0.0, wood=False):
    m = bpy.data.materials.get(name)
    if m is not None:
        return m
    if metallic > 0.0 and name.startswith(PAINTED_METAL) and os.environ.get("IR_PAINTED_METAL", "1") != "0":
        metallic = 0.0; rough = max(rough, 0.35)
    elif os.environ.get("IR_PAINTED_METAL", "1") != "0":
        metallic = 1.0 if metallic >= 0.5 else 0.0              # metallic is a binary material property (Burley 2012); a constant 0.3-0.6 is neither
                                                                # paint nor metal. Intermediate values live only in wear masks (paint_wear.py).
    m = bpy.data.materials.new(name); m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*rgb, 1); b.inputs["Roughness"].default_value = rough
    b.inputs["Metallic"].default_value = metallic
    if transmission:
        b.inputs["Transmission Weight"].default_value = transmission
    if transmission or not SURFACE_DETAIL:
        if wood:
            _grain(m, rgb)
        return m
    kind = _scan_kind(name, metallic, wood)
    if not (kind and _scan(m, rgb, rough, kind, name)):          # a scanned surface where one fits, else the procedural detail
        _grain(m, rgb) if wood else _detail(m, rgb, rough, metallic, name)
    return m


# user 2026-10-17 'generated objects look too smooth': flat colours -> scanned PBR (texturecan) luminance on wood / metal / fabric at
# 60% contrast under our own colour, a procedural detail on the rest, and 3 mm bevels on every procedural mesh. A/B on floor G r36:
# shader-only noise was invisible at 512 px under the denoiser (mean |d| 0.5 grey levels); scans + bevels read as real oak and
# brushed steel. IR_SURFACE_DETAIL=0 restores the flat look.
SURFACE_DETAIL = os.environ.get("IR_SURFACE_DETAIL", "1") != "0"
DRAPE = os.environ.get("IR_DRAPE", "1") != "0"        # cloth sim for boutique garments
PLANT_LIB = Path("/jarvis/project/robomituba/data/plant_library")
_TC = "/bean/ir_pbr_assets/texturecan_environment_merged_v1/texturecan/texturecan_"
_TS = "/bean/ir_pbr_assets/texturecan_staging_v1/assets/texturecan_"   # the full staging set (497): plastics, paper, more metals
SCANS = {"wood": (_TC + "wood_0002", _TC + "wood_0054"),       # continuous grain: the library's planks/parquet/dark ebony read as
         "metal": (_TC + "metal_0024", _TC + "metal_0038", _TC + "metal_0058", _TC + "metal_0062",   # floorboards or turned light oak
                   _TS + "metal_0042"),   # black (A/B pbr1-pbr2); staging metal_0009/0014 are mottled: fridge fronts read
                                          # as 'crumpled foil or stone' (floor J r28)
         "fabric": (_TC + "fabric_0022", _TC + "fabrics_0076", _TC + "fabrics_0085"),   # brushed/plain metal, plain weaves
         "laminate": (_TC + "wood_0002", _TC + "wood_0054"),     # desk / table / counter tops: a faint grain under the top's own colour
         "paint": (_TC + "metal_0024", _TC + "metal_0038"),      # painted cabinet, locker and panel fronts: smooth scans only (the brushed
                                                                 # ones striped a blue locker -- user mark 'too much texture', 2026-10-17)
         "card": (_TS + "paper_0008",),                         # kraft board: 228 plain cartons in floors I/J (census 10-17)
         "plastic": (_TS + "plastic_0003", _TS + "plastic_0005", _TS + "plastic_0007", _TS + "plastic_0021")}
# stone (user 2026-10-17: 'find stone in TextureCan'): the staging set already holds all 18 marble and 8 rock sets; nothing more to download
SCANS["stone"] = (_TS + "rock_0005", _TS + "marble_0011", _TS + "marble_0010")          # grey slab rock, travertine, speckled granite
SCANS["marble_black"] = (_TS + "marble_0007", _TS + "marble_0012")                      # black marble with white veins (podiums, black tops)
SCANS["marble_white"] = (_TS + "marble_0008",)                                           # white marble (white stone tops)
SCAN_TILE = {"stone": 0.8, "marble_black": 1.0, "marble_white": 1.0, "wood": 1.0, "metal": 0.8, "fabric": 0.4, "card": 0.6, "plastic": 0.5, "laminate": 0.9, "paint": 1.2}   # metres per tile
SCAN_CONTRAST = {"stone": 0.55, "marble_black": 0.9, "marble_white": 0.8, "laminate": 0.4, "paint": 0.22}                # share of the scan's luminance variation kept (default 0.6)
_SCAN_MEAN = {}


def _scan_kind(name, metallic, wood):
    n_ = name.lower()
    if "black_stone" in n_ or "black_marble" in n_ or "marble_black" in n_:
        return "marble_black"
    if "white_stone" in n_ or "white_marble" in n_:
        return "marble_white"
    if any(k in n_ for k in ("slab", "limestone", "ir_stone", "plinth", "travertine")):
        return "stone"
    if any(k in n_ for k in ("kit_front_steel", "kit_body_steel", "_pt_steel", "_ms_steel", "_bf_steel", "ir_kit_fridge", "ir_kit_steel", "ir_lr_steel", "ir_ot_", "ir_lab_")):    # a commercial steel run / prep table: the SMOOTH metal scans at low contrast (the metal set read 'mottled grey stone' on G r49)
        return "paint"
    if not wood and any(k in n_ for k in ("desk_top", "conf_top", "disp_top", "checkout_top", "counter_top", "work_top", "table_top")) and "stone" not in n_:
        return "laminate"
    if any(k in n_ for k in ("locker", "pantry_cab", "office_shelf", "desk_panel", "reception_front", "cabinet", "ac_white")):
        return "paint"
    if metallic > 0.5 or any(k in n_ for k in ("steel", "chrome", "metal", "alu")):
        return "metal"
    if wood:
        return "wood"
    if any(k in n_ for k in ("fabric", "cushion", "upholst", "seat", "banquette", "felt", "towel")):
        return "fabric"
    if any(k in n_ for k in ("cardboard", "kraft", "carton", "card_")):
        return "card"
    if "pallet_wood" in n_:
        return "wood"
    if any(k in n_ for k in ("plastic", "ir_bin_", "crate", "tub", "monitor", "ladder_grip")):
        return "plastic"
    return None


def _scan(m, rgb, rough, kind, name):
    import zlib
    d = SCANS[kind][zlib.crc32(name.encode()) % len(SCANS[kind])] + "/"
    if not os.path.isfile(d + "base_color.jpg"):
        return False
    nt = m.node_tree; N, L = nt.nodes, nt.links; b = N["Principled BSDF"]
    src = b.inputs["Base Color"].links[0].from_socket if b.inputs["Base Color"].is_linked else None   # a per-object ramp (cardboard)
    tc = N.new("ShaderNodeTexCoord"); mp = N.new("ShaderNodeMapping"); s_ = 1.0 / SCAN_TILE[kind]
    mp.inputs["Scale"].default_value = (s_, s_, s_); L.new(tc.outputs["Object"], mp.inputs["Vector"])
    def tex(f, color):
        im = bpy.data.images.load(d + f, check_existing=True); im.colorspace_settings.name = "sRGB" if color else "Non-Color"
        if (d + f) not in _SCAN_MEAN:
            import numpy as np
            px = np.array(im.pixels[:], dtype=np.float32).reshape(-1, im.channels)[::97, :3]
            _SCAN_MEAN[d + f] = float((px @ np.array([0.2126, 0.7152, 0.0722], np.float32)).mean()) or 1.0
        t = N.new("ShaderNodeTexImage"); t.image = im; t.projection = "BOX"; t.projection_blend = 0.3
        L.new(mp.outputs["Vector"], t.inputs["Vector"]); return t, _SCAN_MEAN[d + f]
    bc, mean = tex("base_color.jpg", True)
    bw = N.new("ShaderNodeRGBToBW"); L.new(bc.outputs["Color"], bw.inputs["Color"])
    c_ = SCAN_CONTRAST.get(kind, 0.6)
    k_ = N.new("ShaderNodeMath"); k_.operation = "MULTIPLY_ADD"; k_.inputs[1].default_value = c_ / mean; k_.inputs[2].default_value = 1.0 - c_
    L.new(bw.outputs["Val"], k_.inputs[0])                        # 0.4 + 0.6 lum/mean: the grain at 60% contrast, mean 1
    cc = N.new("ShaderNodeCombineColor"); [L.new(k_.outputs["Value"], cc.inputs[i]) for i in range(3)]
    mul = N.new("ShaderNodeMix"); mul.data_type = "RGBA"; mul.blend_type = "MULTIPLY"; mul.inputs["Factor"].default_value = 1.0
    mul.inputs[6].default_value = (*rgb, 1); L.new(cc.outputs["Color"], mul.inputs[7]); L.new(mul.outputs[2], b.inputs["Base Color"])
    if src is not None:
        L.new(src, mul.inputs[6])
    rt, rmean = tex("roughness.jpg", False)
    rm = N.new("ShaderNodeMath"); rm.operation = "MULTIPLY"; rm.use_clamp = True; rm.inputs[1].default_value = rough / rmean
    L.new(rt.outputs["Color"], rm.inputs[0]); L.new(rm.outputs["Value"], b.inputs["Roughness"])
    nm, _ = tex("normal_gl.png", False); nn = N.new("ShaderNodeNormalMap")
    L.new(nm.outputs["Color"], nn.inputs["Color"]); L.new(nn.outputs["Normal"], b.inputs["Normal"])
    return True


PRINT_ROOT = Path("/jarvis/project/robomituba/data/venue_refs/prop_textures")


def _pick_print(prefix, key):
    """A generated image of kind `prefix` (whiteboard / screen / poster_health / wall_art / safety_sign / doc / form / nbpage) chosen
    deterministically by `key`, or None when there are none (or surface detail is off): the caller keeps its flat material."""
    if not SURFACE_DETAIL or not PRINT_ROOT.is_dir():
        return None
    fs = sorted(PRINT_ROOT.glob(prefix + "_*.png"))
    if prefix == "poster_health" and "dental-room" in (set(globals().get("FLOOR_VENUES") or ()) | {VENUE}):
        fs = [f for f in fs if not f.stem.endswith("_05")] or fs                  # no Snellen eye chart (poster_health_05) on a dental floor (E3 r29 DOM-01)
    return fs[zlib.crc32(f"{prefix}:{key}".encode()) % len(fs)] if fs else None


def _printed(path, rgb, rough):
    """A matte-to-glossy material carrying one printed image on the UVs of the box faces that use it (whiteboard writing, screen
    content, a poster, a page of text), shared by every object that picked the same image."""
    name = "ir_print_" + path.stem
    m = bpy.data.materials.get(name)
    if m is not None:
        return m
    m = bpy.data.materials.new(name); m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]; b.inputs["Roughness"].default_value = rough
    im = bpy.data.images.load(str(path), check_existing=True); im.colorspace_settings.name = "sRGB"
    t = m.node_tree.nodes.new("ShaderNodeTexImage"); t.image = im; t.extension = "EXTEND"
    m.node_tree.links.new(t.outputs["Color"], b.inputs["Base Color"])
    return m


def _screen(i, kind="desk"):
    """The glass of a monitor / register / wall display: generated screen content when there is some, else the flat dark slab."""
    if STYLE.get("screen_off"):                                   # kit screen_off: every screen is a black glossy panel (hotel TVs: no office dashboard on them)
        m_ = bpy.data.materials.get("ir_screen_off")             # not _flat: that adds the surface-detail noise, which read as mottled stains on a black panel (H2 r12)
        if m_ is None:
            m_ = bpy.data.materials.new("ir_screen_off"); m_.use_nodes = True
            b_ = m_.node_tree.nodes["Principled BSDF"]; b_.inputs["Base Color"].default_value = (0.012, 0.014, 0.018, 1); b_.inputs["Roughness"].default_value = 0.06
        return m_
    pick = {"desk": (1, 2, 3, 4, 8), "register": (7,), "wall": (3, 5)}[kind]            # not 6: a store-security camera mosaic (B r22: a CCTV wall in the meeting room)
    own = {"boutique": "pos_boutique", "pharmacy": "pos_pharmacy", "convenience": "pos_grocery", "grocery": "pos_grocery"}.get(VENUE)
    if kind == "register" and own and _pick_print(own, f"{kind}{i}") is not None:     # the shop's own goods: the café POS (coffee, tea, cookie)
        return _printed(_pick_print(own, f"{kind}{i}"), (0.02, 0.03, 0.05), 0.15)    # on a boutique till read as 'a strange texture' (user marks)
    path = _pick_print("screen", f"{kind}{i}")
    if path is not None:
        want = [x for x in PRINT_ROOT.glob("screen_*.png") if int(x.stem.split("_")[1]) in pick]
        path = want[zlib.crc32(f"{kind}{i}".encode()) % len(want)] if want else path
        return _printed(path, (0.02, 0.03, 0.05), 0.15)
    return _flat("ir_pos_screen", (0.02, 0.03, 0.05), 0.15)


def _poster_prefix():
    fv = set(globals().get("FLOOR_VENUES") or ()) | {VENUE}
    if "dental-room" in fv and sorted(PRINT_ROOT.glob("poster_dental_*.png")):         # a dental floor: tooth-care posters, not the Snellen eye chart (poster_health_05) of the general set (E3 r28 DOM-01)
        return "poster_dental"
    if fv & {"clinic-reception", "exam-room", "dental-room", "physio-room", "pharmacy"}:
        return "poster_health"
    if "warehouse" in fv:
        return "safety_sign"
    return "wall_art"


def _bevel(o):
    """3 mm rounded edges: razor-sharp box edges are the CG tell next to flat colours (user 2026-10-17)."""
    if SURFACE_DETAIL:
        md = o.modifiers.new("ir_bevel", "BEVEL"); md.width = 0.003; md.segments = 2; md.limit_method = "ANGLE"


def _detail(m, rgb, rough, metallic, name):
    """Surface detail on a flat colour (user 2026-10-17: 'generated objects look too smooth'), shader-only, object space:
    a slow +-6% colour and +-15% roughness drift, and a fine bump whose pattern follows the material class -- hairline streaks on
    metal, a weave on fabric, fibre on card/paper, orange-peel on paint/plastic, a faint waviness on glossy ceramic.
    No AO or edge darkening in the colour: it would leak lighting into the albedo ground truth."""
    nt = m.node_tree; N, L = nt.nodes, nt.links
    b = N["Principled BSDF"]
    n_ = name.lower()
    kind = ("metal" if metallic > 0.5 else "fabric" if any(k in n_ for k in ("fabric", "cushion", "upholst", "seat", "towel", "apron", "felt"))
            else "fibre" if any(k in n_ for k in ("card", "kraft", "paper", "box", "carton")) else "gloss" if rough < 0.15 else "paint")
    tc = N.new("ShaderNodeTexCoord")
    slow = N.new("ShaderNodeTexNoise"); slow.inputs["Scale"].default_value = 3.0; slow.inputs["Detail"].default_value = 3.0
    L.new(tc.outputs["Object"], slow.inputs["Vector"])
    col = N.new("ShaderNodeMapRange"); col.data_type = "FLOAT"
    col.inputs["To Min"].default_value, col.inputs["To Max"].default_value = 0.88, 1.1
    mot = N.new("ShaderNodeTexNoise"); mot.inputs["Scale"].default_value = 25.0; mot.inputs["Detail"].default_value = 8.0   # mottling
    L.new(tc.outputs["Object"], mot.inputs["Vector"])
    both = N.new("ShaderNodeMath"); both.operation = "MULTIPLY_ADD"; both.inputs[1].default_value = 0.5
    L.new(mot.outputs["Fac"], both.inputs[0]); L.new(slow.outputs["Fac"], both.inputs[2])   # slow + mottling/2, ~0.25..1.25
    col.inputs["From Min"].default_value, col.inputs["From Max"].default_value = 0.35, 1.15
    L.new(both.outputs["Value"], col.inputs["Value"])
    mul = N.new("ShaderNodeMix"); mul.data_type = "RGBA"; mul.blend_type = "MULTIPLY"; mul.inputs["Factor"].default_value = 1.0
    mul.inputs[6].default_value = (*rgb, 1)
    cc = N.new("ShaderNodeCombineColor"); [L.new(col.outputs["Result"], cc.inputs[i]) for i in range(3)]
    L.new(cc.outputs["Color"], mul.inputs[7]); L.new(mul.outputs[2], b.inputs["Base Color"])
    rr = N.new("ShaderNodeMapRange"); rr.inputs["To Min"].default_value, rr.inputs["To Max"].default_value = rough * 0.75, min(1.0, rough * 1.25)
    rr.inputs["From Min"].default_value, rr.inputs["From Max"].default_value = 0.35, 1.15
    L.new(both.outputs["Value"], rr.inputs["Value"]); L.new(rr.outputs["Result"], b.inputs["Roughness"])
    mp = N.new("ShaderNodeMapping"); L.new(tc.outputs["Object"], mp.inputs["Vector"])
    if kind == "fabric":
        tex = N.new("ShaderNodeTexWave"); tex.wave_type = "BANDS"; tex.bands_direction = "DIAGONAL"; tex.inputs["Scale"].default_value = 120.0
        strength = 0.4
    else:
        tex = N.new("ShaderNodeTexNoise"); tex.inputs["Detail"].default_value = 6.0
        tex.inputs["Scale"].default_value, strength = {"metal": (80.0, 0.15), "fibre": (120.0, 0.3), "gloss": (15.0, 0.05),
                                                       "paint": (80.0, 0.2)}[kind]   # ~1 cm features: at 400 the
        # bump sat below a pixel and the A/B showed no change (G r36 close-ups, mean |d| 0.5 grey levels, 2026-10-17)
        if kind == "metal":                                      # hairline brushing: stretched along one axis
            mp.inputs["Scale"].default_value = (60.0, 1.0, 1.0)
    L.new(mp.outputs["Vector"], tex.inputs["Vector"])
    bump = N.new("ShaderNodeBump"); bump.inputs["Strength"].default_value = strength; bump.inputs["Distance"].default_value = 0.002
    L.new(tex.outputs["Fac"], bump.inputs["Height"]); L.new(bump.outputs["Normal"], b.inputs["Normal"])


# a block stroke font for shop signs: (x, z, w, h) in a unit cell centred on 0; w or h 0 = one stroke thick
_SEG = {"L": (-0.5, 0, 0, 1), "R": (0.5, 0, 0, 1), "Lt": (-0.5, 0.25, 0, 0.5), "Lb": (-0.5, -0.25, 0, 0.5), "Rt": (0.5, 0.25, 0, 0.5),
        "Rb": (0.5, -0.25, 0, 0.5), "T": (0, 0.5, 1, 0), "M": (0, 0, 1, 0), "B": (0, -0.5, 1, 0), "C": (0, 0, 0, 1), "Cb": (0, -0.25, 0, 0.5)}
_STROKES = {ch: [_SEG[k] for k in segs.split()] for ch, segs in {
    "A": "L R T M", "C": "L T B", "D": "L Rb Rt T B", "E": "L T M B", "F": "L T M", "H": "L R M", "I": "C", "L": "L B", "O": "L R T B",
    "P": "L Rt T M", "S": "Lt Rb T M B", "T": "T C", "U": "L R B",
    "R": "L Rt T M Rb", "Y": "Lt Rt M Cb", "B": "L R T M B", "G": "L T B Rb"}.items()}      # R / Y / B / G: DAIRY, BREAD, BEER, GIFT for kit header_words
HEADER_WORDS = ("FOOD", "COLD", "TEA", "SOUP", "DELI", "SALE", "CUPS", "SODA", "HOT", "SALAD")   # only letters the font has


WOODS = ("butcher_block", "light_wood", "dark_wood")


def _grain(m, rgb):
    """Wood grain on a flat colour (style eval 2026-10-16: 'chairs and tables look like clay with a flat tint, no wood grain'):
    distorted wave bands in object space mix the colour with a 35% darker late wood, plus a faint bump of the same bands."""
    nt = m.node_tree; N, L = nt.nodes, nt.links
    b = N["Principled BSDF"]
    tc = N.new("ShaderNodeTexCoord"); wv = N.new("ShaderNodeTexWave"); mix = N.new("ShaderNodeMix"); bump = N.new("ShaderNodeBump")
    wv.wave_type = "BANDS"; wv.bands_direction = "X"
    wv.inputs["Scale"].default_value = 22.0; wv.inputs["Distortion"].default_value = 4.0; wv.inputs["Detail"].default_value = 4.0
    wv.inputs["Detail Scale"].default_value = 2.0                # fine grain (style eval H: 'oversized wavy procedural grain')
    mix.data_type = "RGBA"
    mix.inputs[6].default_value = (*rgb, 1); mix.inputs[7].default_value = (*(c * 0.65 for c in rgb), 1)
    bump.inputs["Strength"].default_value = 0.08; bump.inputs["Distance"].default_value = 0.002
    L.new(tc.outputs["Object"], wv.inputs["Vector"]); L.new(wv.outputs["Fac"], mix.inputs["Factor"])
    L.new(mix.outputs[2], b.inputs["Base Color"]); L.new(wv.outputs["Fac"], bump.inputs["Height"]); L.new(bump.outputs["Normal"], b.inputs["Normal"])


STYLE = {}                                                       # set by realize from the plan's venue style
_ROOM_PICK = {}                                                  # per-scene picks shared by every instance (one process per scene)
VENUE = ""                                                       # set by realize: cafe / grocery / ... (fixture density)
from room_planner.styles import COUNTER_FRONTS, COUNTER_TOPS  # noqa: E402  (bpy-free: the reference reader enumerates them)



def _parts_object(name, groups):
    """One object, one material slot per group: groups = [(material, [(cx, cy, cz, sx, sy, sz), ...]), ...]."""
    import bmesh
    bm = bmesh.new(); bm.loops.layers.uv.verify()
    for slot, (mat, parts) in enumerate(groups):
        for cx, cy, cz, sx, sy, sz in parts:
            r = bmesh.ops.create_cube(bm, size=1.0, calc_uvs=True)    # unit UVs per face: a printed image sits on a board or screen
            bmesh.ops.scale(bm, vec=(sx, sy, sz), verts=r["verts"])
            _face_uvs(bm, r["verts"])
            bmesh.ops.translate(bm, vec=(cx, cy, cz), verts=r["verts"])
            for f in {f for v in r["verts"] for f in v.link_faces}:
                f.material_index = slot
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    for mat, _ in groups:
        me.materials.append(mat)
    o = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(o)
    _bevel(o)
    return o


class TaskChairFactory:
    """Office task chair (front +X): five-star base on casters, gas column, upholstered seat, mesh-look back, armrests (floors J r9 /
    E3 r8: the Infinigen office chair came out as 'a white shell seat' or 'a blue lab stool' -- café or lab, not an office)."""
    def __init__(self, seed):
        r = random.Random(seed)
        self.c = _ROOM_PICK.setdefault("task_chair", r.choice(((0.05, 0.05, 0.06), (0.2, 0.21, 0.23), (0.08, 0.12, 0.2))))

    def spawn_asset(self, i):
        fab = _flat(f"ir_task_fabric_{int(self.c[2] * 100)}", self.c, 0.8); blk = _flat("ir_black_plastic", (0.04, 0.04, 0.045), 0.5)
        steel = _flat("ir_desk_frame", (0.75, 0.75, 0.76), 0.35, 0.8)
        spokes = [("box", (0.16 * math.cos(a), 0.16 * math.sin(a), 0.07), (0.32, 0.04, 0.03), (0, 0, a)) for a in [k * 2 * math.pi / 5 for k in range(5)]]
        casters = [("cyl", (0.31 * math.cos(a), 0.31 * math.sin(a), 0.03), (0.025, 0.025, 0.04), (math.pi / 2, 0, a)) for a in [k * 2 * math.pi / 5 for k in range(5)]]
        return _prims(f"TaskChairFactory({i}).spawn_asset({i})", [
            (blk, spokes + casters + [("box", (-0.02, 0, 0.44), (0.3, 0.3, 0.03), (0, 0, 0)),
                                      ("box", (-0.24, 0, 0.6), (0.03, 0.08, 0.3), (0, -0.1, 0))] +
                  [("box", (0.0, sy * 0.25, 0.62), (0.26, 0.05, 0.03), (0, 0, 0)) for sy in (1, -1)] +
                  [("box", (-0.05, sy * 0.25, 0.54), (0.03, 0.03, 0.16), (0, 0, 0)) for sy in (1, -1)]),
            (steel, [("cyl", (0, 0, 0.26), (0.025, 0.025, 0.34), (0, 0, 0))]),
            (fab, [("rbox", (0.0, 0, 0.48), (0.48, 0.48, 0.08), (0, 0, 0))] + ([("rbox", (-0.27, 0, 0.88), (0.06, 0.45, 0.55), (0, -0.12, 0))] if STYLE.get("task_chair_style") != "mesh" else []))] +
            ([(blk, [("box", (-0.27, sy * 0.225, 0.88), (0.04, 0.03, 0.56), (0, -0.12, 0)) for sy in (1, -1)] + [("box", (-0.27 + 0.003 * (z - 0.88), 0, z), (0.04, 0.45, 0.03), (0, -0.12, 0)) for z in (0.6, 1.16)] +
                       [("box", (-0.268, 0, 0.88), (0.008, 0.43, 0.54), (0, -0.12, 0))] +                                      # a continuous fine-mesh sheet (B r22: 'open square-grid backs, want fine mesh') ...
                       [("box", (-0.27 + 0.003 * (z - 0.88), 0, z), (0.014, 0.43, 0.004), (0, -0.12, 0)) for z in [0.64 + 0.035 * k for k in range(14)]])] if STYLE.get("task_chair_style") == "mesh" else []))


class CheckoutCounterFactory:
    """Shop checkout (front +X = the customer side): a grey laminate till counter with a dark top and a kick plinth, an impulse rack
    of small coloured packs on the customer end, a back-counter shelf unit is the plan's backbar_shelf (floor I r11: 'a slatted café
    counter as the till', 3 of 3)."""
    def __init__(self, seed):
        r = random.Random(seed); self.L = r.choice((1.6, 2.0)); self.c = r.choice(((0.55, 0.57, 0.6), (0.82, 0.82, 0.8)))

    def spawn_asset(self, i):
        L, D, H = self.L, 0.7, 0.95
        cb_, ct_ = STYLE.get("checkout_body_rgb"), STYLE.get("checkout_top_rgb")           # kit: a timber front panel + white top (I r34 refs: 'light oak front, white top'), not grey laminate + dark top
        body = _flat(f"ir_checkout_{int(self.c[0] * 100)}", self.c, 0.4) if not cb_ else _flat(f"ir_checkout_wood_{int(cb_[0] * 100)}", tuple(cb_), 0.5, wood=True)
        top = _flat("ir_checkout_top", (0.06, 0.06, 0.07), 0.3) if not ct_ else _flat(f"ir_checkout_top_{int(ct_[0] * 100)}", tuple(ct_), 0.3)
        wire = _flat("ir_black_metal", (0.03, 0.03, 0.03), 0.4, 1.0)
        packs = [_flat(f"ir_pack_{j}", c, 0.5) for j, c in enumerate(((0.8, 0.1, 0.1), (0.95, 0.75, 0.1), (0.1, 0.4, 0.75), (0.15, 0.6, 0.25)))]
        groups = [(body, [(0, 0, H / 2 - 0.02, D, L, H - 0.04)]), (top, [(0, 0, H - 0.02, D + 0.04, L + 0.04, 0.04), (D / 2 - 0.01, 0, 0.05, 0.02, L, 0.1)]),
                  (wire, [(D / 2 + 0.15, L / 2 - 0.25, 0.45 + z, 0.3, 0.4, 0.01) for z in (0.0, 0.25, 0.5)] +
                         [(D / 2 + 0.15, L / 2 - 0.25 + sy * 0.2, 0.45, 0.3, 0.01, 0.9) for sy in (1, -1)] +
                         [(D / 2 + 0.15, L / 2 - 0.25, 0.22, 0.04, 0.04, 0.45)])]
        for j in range(12):                                      # packs on the three rack levels
            lvl, k = j // 4, j % 4
            groups.append((packs[(j + lvl) % 4], [(D / 2 + 0.15, L / 2 - 0.4 + k * 0.1, 0.45 + lvl * 0.25 + 0.06, 0.12, 0.07, 0.11)]))
        return _parts_object(f"CheckoutCounterFactory({i}).spawn_asset({i})", groups)


def _brick_material(name, rgb, h=0.065, ln=0.215, mortar=0.01):
    """A red-brick running-bond material: a 1 m x 1 m tileable bake (cached under data/venue_refs/tile_cache), sampled triplanar in world metres like tile_walls."""
    import numpy as np
    from PIL import Image
    m = bpy.data.materials.get(name)
    if m is not None:
        return m
    cache = Path("/jarvis/project/robomituba/data/venue_refs/tile_cache"); cache.mkdir(parents=True, exist_ok=True)
    key = f"brick_{int(rgb[0] * 100)}_{int(rgb[1] * 100)}_{int(rgb[2] * 100)}.png"; out = cache / key
    if not out.exists():
        px = 1024; rng = np.random.default_rng(7)
        yy, xx = np.mgrid[0:px, 0:px] / px
        rows = 15; courses = np.floor(yy * rows).astype(int); fy = yy * rows - courses
        shift = (courses % 2) * 0.5; bx = (xx * 5 + shift) % 5; bi = np.floor(bx).astype(int); fx = bx - bi
        tone = rng.random((rows, 5)) * 0.35 - 0.12
        t = tone[courses % rows, (bi + (courses % 2) * 0) % 5]
        col = np.array(rgb)[None, None, :] * (1.0 + t[..., None] * 0.9)
        grain = (rng.random((px, px, 1)) - 0.5) * 0.12
        col = col * (1 + grain)
        mort = (fy < mortar / h * 0.9) | (fx < mortar / ln * 1.0)
        col = np.where(mort[..., None], np.array([0.62, 0.6, 0.56])[None, None, :], col)
        Image.fromarray((np.clip(col, 0, 1) * 255).astype(np.uint8), "RGB").save(out)
    import tile_walls as _tw
    img = bpy.data.images.load(str(out), check_existing=True); img.colorspace_settings.name = "sRGB"
    return _tw._material(name, img, 1.0, 0.8)


class CafeCounterFactory:
    """A service counter (front +X like Infinigen): body with a slatted or tiled front, an overhanging top; 1.8-3.2 m long."""
    def __init__(self, seed):
        r = random.Random(seed)
        self.L = r.uniform(*STYLE["counter_len_m"]) if STYLE.get("counter_len_m") else r.uniform(1.8, 3.2)   # the kit's counter length range (S8: a long ribbed counter)
        self.front = STYLE.get("counter_front") or r.choice(sorted(COUNTER_FRONTS))
        self.top = STYLE.get("counter_top") or r.choice(sorted(COUNTER_TOPS))
        self.slats = any(k in self.front for k in ("slat", "fluted", "panel"))

    def spawn_asset(self, i):
        L, D, H = self.L, 0.65, 1.0
        fr_rgb, fr_r = COUNTER_FRONTS[self.front]; tp_rgb, tp_r = COUNTER_TOPS[self.top]
        tp_r = STYLE.get("counter_top_rough") or tp_r                # the kit's polish (S10: black marble with reflections)
        front = _flat(f"ir_counter_{self.front}", fr_rgb, fr_r)
        if "brick" in self.front:                                # a real BRICK face (H r64: 'counter face should read brick, ours plain red'): baked running-bond image, world-space triplanar
            try:
                front = _brick_material(f"ir_counter_{self.front}_img", fr_rgb)
            except Exception as ex:                              # noqa: BLE001 -- the flat colour stays
                print(f"[proc_assets] brick material skipped: {ex!r}"[:160])
        top = _flat(f"ir_counter_top_{self.top}", tp_rgb, tp_r,
                                                                             metallic=1.0 if self.top == "steel" else 0.0, wood=self.top in WOODS)
        if STYLE.get("counter_curve"):                           # kit counter_curve=<sagitta m>: a gently BOWED counter (G r52 ref: 'curved / ribbed counter with a return'); x(y) = -s (2y/L)^2, fluted front, an integrated glass pastry display at the +y end
            return self._curved(i, L, D, H, front, top, fr_rgb, float(STYLE["counter_curve"]))
        body = [(0, 0, (H - 0.04) / 2, D, L, H - 0.04)]
        if self.slats and "panel" not in self.front:             # vertical slats proud of the front face (+x)
            n = int(L / 0.06)
            body += [(D / 2 + 0.008, -L / 2 + (k + 0.5) * L / n, (H - 0.04) / 2, 0.016, L / n * 0.6, H - 0.1) for k in range(n)]
        else:                                                    # raised panels with a moulding frame (style eval: 'a plain block')
            n = max(2, int(L / 0.6))
            for k in range(n):
                y = -L / 2 + (k + 0.5) * L / n
                body += [(D / 2 + 0.01, y, 0.5, 0.02, L / n - 0.12, 0.62), (D / 2 + 0.005, y, 0.86, 0.01, L / n - 0.06, 0.03),
                         (D / 2 + 0.005, y, 0.14, 0.01, L / n - 0.06, 0.03)]
        return _parts_object(f"CafeCounterFactory({i}).spawn_asset({i})",
                             [(front, body), (top, [(0.03, 0, H - 0.02, D + 0.06, L + 0.04, 0.04)])])


def _counter_curved(self, i, L, D, H, front, top, fr_rgb, sag):
    import math as _m
    n = max(8, int(L / 0.45)); seg = L / n
    xc = lambda y: -sag * (2 * y / L) ** 2
    ph = lambda y: _m.atan(8 * sag * y / (L * L))            # tan(phi) = -dx/dy rotated: the segment's heading
    bodyp, topp, ribs, glassp, pastry_a, pastry_b = [], [], [], [], [], []
    case0 = L / 2 - 1.1 if STYLE.get("counter_pastry") == "integrated" else L + 1.0                 # the display section's start along y
    glass = _flat("ir_ccv_glass", (0.9, 0.95, 0.96), 0.05, transmission=1.0); dough = (0.78, 0.5, 0.2); cream = (0.95, 0.9, 0.78)
    for k in range(n):
        y = -L / 2 + (k + 0.5) * seg; x = xc(y); a = ph(y)
        ny, nx = _m.cos(a), -_m.sin(a)                       # the segment's +x normal in the plane (front direction)
        in_case = y > case0
        bodyp.append(("box", (x, y, (H - 0.04) / 2), (D, seg * 1.06, H - 0.04), (0, 0, a)))
        topp.append(("box", (x + 0.03 * ny, y + 0.03 * (-nx) * 0, H - 0.02), (D + 0.06, seg * 1.06, 0.04), (0, 0, a)))
        if in_case:
            glassp.append(("box", (x + (D / 2 + 0.005) * ny, y, 0.62), (0.012, seg, 0.5), (0, 0, a)))
        else:
            for sub in (-1, 1):                              # two fluting ribs per segment, proud of the front
                ribs.append(("box", (x + (D / 2 + 0.01) * ny - sub * seg * 0.22 * (-nx) * 0, y + sub * seg * 0.22, (H - 0.04) / 2), (0.02, seg * 0.38, H - 0.1), (0, 0, a)))
    if STYLE.get("counter_pastry") == "integrated":          # trays + pastries behind the glass (inside the counter body: the body is cut open at the top of the section)
        ks = [k for k in range(n) if -L / 2 + (k + 0.5) * seg > case0]
        for k in ks:
            y = -L / 2 + (k + 0.5) * seg; x = xc(y)
            for z in (0.7, 0.9):
                topp.append(("box", (x + 0.0, y, z), (D - 0.1, seg * 0.95, 0.012), (0, 0, ph(y))))
                for j in range(3):
                    (pastry_a if (j + k) % 2 else pastry_b).append(("sph", (x + 0.05 * (j - 1), y + 0.1 * (j - 1), z + 0.04), (0.045, 0.04, 0.03), (0, 0, 0)))
    fm = front
    groups = [(fm, bodyp + ribs), (top, topp), (glass, glassp)]
    if pastry_a:
        groups += [(_flat("ir_ccv_dough", dough, 0.6), pastry_a), (_flat("ir_ccv_cream", cream, 0.6), pastry_b)]
    o = _prims(f"CafeCounterFactory({i}).spawn_asset({i})", groups)
    o["ir_curve_s"] = sag; o["ir_curve_L"] = L
    return o


CafeCounterFactory._curved = _counter_curved


class CafeTableFactory:
    """Bistro table: round-ish (octagonal) or square top on a pedestal, 0.6-0.8 m, 0.75 m high."""
    def __init__(self, seed):
        r = random.Random(seed)
        self.w = r.uniform(*STYLE["cafe_table_w"]) if STYLE.get("cafe_table_w") else r.uniform(0.6, 0.8)      # kit cafe_table_w=[min,max]: fewer, LARGER tables (H r66)
        self.round_ = STYLE.get("table_shape") == "round" or (STYLE.get("table_shape") == "mixed" and r.random() < 0.5)     # 'mixed': round central tables + square two-tops by the banquette
        self.top = STYLE.get("table_top") if STYLE.get("table_top") in COUNTER_TOPS else r.choice(("white_stone", "black_stone", "butcher_block"))
        pal_ = STYLE.get("table_top_palette")                  # kit table_top_palette=[[r,g,b],...]: each table gets one painted colour (M refs: round colourful food-court tables)
        self.col = tuple(r.choice(pal_)) if pal_ else None

    def spawn_asset(self, i):
        w = self.w
        top = _flat(f"ir_counter_top_{self.top}", *COUNTER_TOPS[self.top], wood=self.top in WOODS) if not self.col else _flat(f"ir_ct_col_{int(self.col[0] * 100)}_{int(self.col[1] * 100)}", self.col, 0.4); metal = _flat("ir_black_metal", (0.03, 0.03, 0.03), 0.4, 1.0)
        if STYLE.get("chair_style") == "bentwood" or self.round_:   # round bistro tops (style eval)
            return _prims(f"CafeTableFactory({i}).spawn_asset({i})",
                          [(top, [("cyl", (0, 0, 0.745), (w / 2, w / 2, 0.03), (0, 0, 0))]),
                           (metal, [("cyl", (0, 0, 0.37), (0.03, 0.03, 0.7), (0, 0, 0)), ("cyl", (0, 0, 0.015), (0.22, 0.22, 0.03), (0, 0, 0))])])
        return _parts_object(f"CafeTableFactory({i}).spawn_asset({i})",
                             [(top, [(0, 0, 0.74, w, w, 0.03)]),
                              (metal, [(0, 0, 0.37, 0.06, 0.06, 0.70), (0, 0, 0.01, 0.45, 0.06, 0.02), (0, 0, 0.01, 0.06, 0.45, 0.02)])])


class CafeChairFactory:
    """A café chair in the reference's style (cafe r3: ABO pools gave grey/white upholstered chairs for every style). Front +X.
    bentwood: dark curved hoop back, round seat, splayed legs; light_wood: pale oak, spindle-free shell back; metal_bistro: black steel
    seat and back with a straight back."""
    def __init__(self, seed, style=None):
        r = random.Random(seed)
        self.style = style or STYLE.get("chair_style") or r.choice(("bentwood", "light_wood", "metal_bistro"))
        if self.style not in ("bentwood", "light_wood", "metal_bistro", "upholstered"):   # 'mixed': a café mixes two bistro families, never office chairs
            self.style = r.choice(("metal_bistro", "metal_bistro", "bentwood"))   # dark bistro family (style eval G: blond chairs in a brick cafe)

    def spawn_asset(self, i):
        st = self.style
        col = {"bentwood": ((0.035, 0.02, 0.012), 0.35, 0.0), "light_wood": ((0.62, 0.46, 0.3), 0.5, 0.0),   # near-black: reads dark under 2300 K
               "metal_bistro": ((0.04, 0.04, 0.045), 0.4, 1.0)}.get(st, ((0.12, 0.07, 0.04), 0.45, 0.0))
        nm_ = f"ir_chair_{st}"
        if STYLE.get("chair_rgb") and st in ("metal_bistro", "light_wood"):                    # kit chair_rgb: painted chairs in one colour (I r35 refs: green staff-room chairs)
            col = (tuple(STYLE["chair_rgb"]), 0.5, 0.0); nm_ = f"ir_chair_{st}_{int(col[0][0] * 100)}_{int(col[0][1] * 100)}"
        m = _flat(nm_, col[0], col[1], col[2], wood=st in ("bentwood", "light_wood") and "chair_rgb" not in STYLE)
        legs = [("cyl", (sx * 0.17, sy * 0.17, 0.22), (0.016, 0.014, 0.45), (sy * 0.06, -sx * 0.06, 0)) for sx in (1, -1) for sy in (1, -1)]
        if st == "upholstered":                                  # kit chair_style=upholstered (floor H: mustard velvet ARMCHAIRS on black steel legs): round seat, a wraparound curved back with arms
            up = tuple(STYLE.get("upholstery_srgb") or (0.85, 0.6, 0.15))
            frame = _flat("ir_chair_up_frame", (0.03, 0.03, 0.035), 0.4, 1.0); fab = _flat(f"ir_chair_up_{int(up[0] * 100)}_{int(up[1] * 100)}", up, 0.85)
            lg = [("cyl", (sx * 0.19, sy * 0.19, 0.2), (0.014, 0.011, 0.42), (sy * 0.08, -sx * 0.08, 0)) for sx in (1, -1) for sy in (1, -1)]
            arm = [("rbox", (-0.14 + 0.0, sy * 0.25, 0.64), (0.34, 0.07, 0.2), (0, 0, 0)) for sy in (1, -1)] + [("rbox", (-0.2, 0, 0.7), (0.08, 0.5, 0.34), (0, 0.1, 0))]
            if STYLE.get("upholstered_form") == "club":                  # kit upholstered_form=club: a leather CLUB armchair (S33 r3: 'blocky, cuboid arms, flat seats'): a deep seat cushion, rolled arms, a tall tilted back, short dark legs
                lg = [("cyl", (sx * 0.2, sy * 0.2, 0.1), (0.022, 0.016, 0.2), (sy * 0.12, -sx * 0.12, 0)) for sx in (1, -1) for sy in (1, -1)]
                body = [("rbox", (0.0, 0, 0.3), (0.56, 0.58, 0.2), (0, 0, 0)), ("rbox", (0.02, 0, 0.44), (0.46, 0.46, 0.14), (0, 0, 0))]                  # base + seat cushion
                body += [("rbox", (-0.02, sy * 0.28, 0.5), (0.5, 0.12, 0.3), (0, 0, 0)) for sy in (1, -1)]                                              # arm bodies
                body += [("cyl", (-0.02, sy * 0.28, 0.67), (0.065, 0.065, 0.5), (0, 1.5708, 0)) for sy in (1, -1)]                                      # arm rolls (a cylinder along x)
                body += [("rbox", (-0.25, 0, 0.62), (0.14, 0.58, 0.5), (0, 0.16, 0))]                                                                    # tall tilted back
                return _prims(f"CafeChairFactory({i}).spawn_asset({i})", [(frame, lg), (fab, body)])
            return _prims(f"CafeChairFactory({i}).spawn_asset({i})", [(frame, lg), (fab, [("rbox", (0, 0, 0.45), (0.5, 0.5, 0.1), (0, 0, 0))] + arm)])
        if st == "bentwood":
            seat = [("cyl", (0, 0, 0.46), (0.21, 0.21, 0.035), (0, 0, 0))]
            back = [("box", (-0.19, sy * 0.15, 0.68), (0.025, 0.025, 0.46), (0, 0, 0)) for sy in (1, -1)] + \
                   [("box", (-0.2, 0, 0.9), (0.025, 0.34, 0.025), (0, 0, 0)), ("box", (-0.2, 0, 0.7), (0.02, 0.3, 0.02), (0, 0, 0))]
        elif st == "metal_bistro" and STYLE.get("chair_round"):      # kit: a rounded steel bistro chair (S6 'black chairs boxy'): round seat, bevelled curved back on two posts, slim splayed legs
            legs = [("cyl", (sx * 0.15, sy * 0.15, 0.22), (0.013, 0.01, 0.45), (sy * 0.1, -sx * 0.1, 0)) for sx in (1, -1) for sy in (1, -1)]
            seat = [("cyl", (0, 0, 0.46), (0.21, 0.21, 0.03), (0, 0, 0))]
            back = [("rbox", (-0.2, 0, 0.7), (0.03, 0.34, 0.2), (0, 0.12, 0))] + [("cyl", (-0.18, sy * 0.14, 0.58), (0.011, 0.01, 0.24), (0, 0.1, 0)) for sy in (1, -1)]
        elif st == "metal_bistro":
            seat = [("box", (0, 0, 0.46), (0.4, 0.4, 0.025), (0, 0, 0))]
            back = [("box", (-0.2, 0, 0.66), (0.025, 0.38, 0.38), (0, 0.08, 0))] + \
                   [("cyl", (-0.19, sy * 0.17, 0.62), (0.011, 0.011, 0.34), (0, 0.08, 0)) for sy in (1, -1)]      # two posts seat -> back: the bare back panel floated in the air (floor C r18, N r1)
        elif STYLE.get("chair_round"):                           # kit: a softly rounded chair (G hall r37: 'the chairs are too square'): round seat, bevelled curved back, slim splayed legs
            legs = [("cyl", (sx * 0.15, sy * 0.15, 0.22), (0.014, 0.011, 0.45), (sy * 0.1, -sx * 0.1, 0)) for sx in (1, -1) for sy in (1, -1)]
            seat = [("cyl", (0, 0, 0.46), (0.22, 0.22, 0.035), (0, 0, 0))]
            back = [("rbox", (-0.2, 0, 0.7), (0.035, 0.36, 0.2), (0, 0.14, 0))] + [("cyl", (-0.17, sy * 0.15, 0.58), (0.012, 0.01, 0.26), (0, 0.12, 0)) for sy in (1, -1)]
        else:
            seat = [("box", (0, 0, 0.46), (0.42, 0.42, 0.03), (0, 0, 0))]
            back = [("box", (-0.2, 0, 0.72), (0.03, 0.4, 0.14), (0, 0.12, 0))] + [("box", (-0.19, sy * 0.17, 0.6), (0.025, 0.025, 0.28), (0, 0, 0)) for sy in (1, -1)]
        groups = [(m, legs + seat + back)]
        if st == "light_wood" and STYLE.get("chair_round") and STYLE.get("upholstery_srgb"):       # G r42 'curved oak chairs with upholstered seats': a cream cushion on the round seat
            u = tuple(STYLE["upholstery_srgb"])
            groups.append((_flat(f"ir_chair_cushion_{int(u[0] * 100)}_{int(u[2] * 100)}", u, 0.85), [("cyl", (0, 0, 0.49), (0.2, 0.2, 0.03), (0, 0, 0))]))
        return _prims(f"CafeChairFactory({i}).spawn_asset({i})", groups)


class BudVaseFactory:
    """A small glass or ceramic vase with 3-7 flowers (style eval floral: 'no flowers on the tables'), 0.15-0.3 m."""
    def __init__(self, seed, big=False):
        r = random.Random(seed); self.r, self.big = r, big
        self.pal = r.choice((((0.85, 0.3, 0.4), (0.95, 0.85, 0.9)), ((0.95, 0.7, 0.2), (0.95, 0.95, 0.9)), ((0.6, 0.2, 0.5), (0.9, 0.5, 0.6)),
                             ((0.95, 0.95, 0.92), (0.75, 0.1, 0.15))))

    def spawn_asset(self, i):
        if STYLE.get("infinigen_plants"):                        # real Infinigen wild-flower stems in the vase (S10: the procedural blossoms read stiff)
            r, big = self.r, self.big
            vase_m = _flat("ir_vase_glass_if" if r.random() < 0.5 else "ir_vase_ceramic_if", (0.85, 0.88, 0.85) if r.random() < 0.5 else (0.2, 0.25, 0.22), 0.1, transmission=0.8 if r.random() < 0.5 else 0.0)
            vh = 0.2 if big else 0.12; vr = 0.07 if big else 0.035
            o = _infinigen_bunch(r, [(vase_m, [("cyl", (0, 0, vh / 2), (vr, vr * 0.75, vh), (0, 0, 0))])], vh, r.randint(9, 13) if big else r.randint(4, 7),
                                 0.5 if big else 0.26, 0.8 if big else 0.4, 0.28 if big else 0.2, f"BudVaseFactory({i}).spawn_asset({i})")
            if o is not None:
                return o
        return self._spawn_procedural(i)

    def _spawn_procedural(self, i):
        r, s_ = self.r, (2.6 if self.big else 1.0)
        hs = 1.5 if self.big else 1.0                                 # blossom size: a big bouquet has MORE heads, not 2.6x balls (S10: 'pink bubbles on green stalks')
        vase = _flat("ir_vase_glass" if r.random() < 0.5 else "ir_vase_ceramic", (0.85, 0.88, 0.85) if r.random() < 0.5 else (0.2, 0.25, 0.22), 0.1,
                     transmission=0.8 if r.random() < 0.5 else 0.0)
        stem = _flat("ir_stem", (0.12, 0.3, 0.1), 0.7); leaf = _flat("ir_leaf", (0.15, 0.38, 0.12), 0.6)
        groups = [(vase, [("cyl", (0, 0, 0.06 * s_), (0.03 * s_, 0.025 * s_, 0.12 * s_), (0, 0, 0))])]
        pal = list(self.pal) + ([(0.97, 0.9, 0.85), (0.93, 0.62, 0.5), (0.98, 0.97, 0.94), (0.55, 0.1, 0.18)] if self.big else [])   # mixed blooms: cream, peach, white, burgundy
        stems, heads, leaves = [], {}, []
        for k in range(r.randint(16, 24) if self.big else r.randint(3, 6)):
            a, t = r.uniform(0, 6.28), r.uniform(0.05, 0.75 if self.big else 0.35)
            h = r.uniform(0.14, 0.24) * (1.6 if self.big else 1.0) * (1.0 if self.big else s_)
            tip = (math.sin(t) * math.cos(a) * h, math.sin(t) * math.sin(a) * h, 0.1 * s_ + math.cos(t) * h)
            stems.append(("cyl", (tip[0] / 2, tip[1] / 2, (0.1 * s_ + tip[2]) / 2), (0.003 * s_, 0.003 * s_, h), (t * math.sin(a), -t * math.cos(a), 0)))
            c = r.choice(pal)
            for j in range(5):                                       # a blossom = a ring of 5 flattened petals round a centre
                pa = 2 * math.pi * j / 5 + a
                heads.setdefault(c, []).append(("sph", (tip[0] + 0.011 * hs * math.cos(pa), tip[1] + 0.011 * hs * math.sin(pa), tip[2]), (0.013 * hs, 0.013 * hs, 0.008 * hs), (0, 0, pa)))
            heads.setdefault((0.9, 0.75, 0.3), []).append(("sph", (tip[0], tip[1], tip[2] + 0.004 * hs), (0.006 * hs, 0.006 * hs, 0.006 * hs), (0, 0, 0)))
            leaves.append(("sph", (tip[0] * 0.6, tip[1] * 0.6, 0.1 * s_ + tip[2] * 0.4), (0.02 * s_, 0.008 * s_, 0.012 * s_), (0, 0, a)))
        groups += [(stem, stems), (leaf, leaves)]
        for c, parts in heads.items():
            groups.append((_flat(f"ir_bloom_{int(c[0] * 100)}_{int(c[1] * 100)}", c, 0.6), parts))
        return _prims(f"BudVaseFactory({i}).spawn_asset({i})", groups)


class FlowerArrangementFactory(BudVaseFactory):
    """A large bouquet for the counter (floral cafés)."""
    def __init__(self, seed):
        super().__init__(seed, big=True)


class HangingPlantFactory:
    """A ceiling-hung trailing plant (pothos): a pot on three cords from a ceiling hook, leaf strands trailing 0.4-0.9 m below it.
    Origin at the hook; the pot hangs `drop` below (nordic / chain refs: hanging plants in every view, renders had none)."""
    def __init__(self, seed, drop=0.7):
        r = random.Random(seed); self.r = r; self.drop = drop
        self.pot = r.choice(((0.85, 0.83, 0.78), (0.6, 0.35, 0.22), (0.12, 0.12, 0.12)))

    def spawn_asset(self, i):
        r, z = self.r, -self.drop
        pot = _flat(f"ir_pot_{int(self.pot[0] * 100)}", self.pot, 0.6); cord = _flat("ir_cord", (0.75, 0.68, 0.55), 0.8)
        leaf = _flat(f"ir_pothos_{i % 3}", ((0.12, 0.32, 0.08), (0.18, 0.4, 0.1), (0.1, 0.26, 0.07))[i % 3], 0.55)
        cords = [("cyl", (0.06 * math.cos(a) / 2, 0.06 * math.sin(a) / 2, z / 2), (0.003, 0.003, abs(z)), (0.12 * math.sin(a), -0.12 * math.cos(a), 0))
                 for a in (0, 2.1, 4.2)]
        leaves = [("sph", (0, 0, z + 0.02), (0.13, 0.13, 0.07), (0, 0, 0))]
        for s_ in range(r.randint(5, 8)):                        # strands over the rim, each a chain of leaves drifting outward
            a = r.uniform(0, 2 * math.pi); L = r.uniform(0.3, 0.6)   # bottom stays above head height
            for k in range(int(L / 0.06)):
                rad = 0.12 + 0.02 * k ** 0.5
                leaves.append(("sph", (rad * math.cos(a) + r.uniform(-0.02, 0.02), rad * math.sin(a) + r.uniform(-0.02, 0.02), z - 0.05 - k * 0.06),
                               (0.035, 0.03, 0.012), (r.uniform(-1, 1), r.uniform(-1, 1), r.uniform(0, 3))))
        return _prims(f"HangingPlantFactory({i}).spawn_asset({i})",
                      [(pot, [("cyl", (0, 0, z - 0.07), (0.08, 0.12, 0.16), (0, 0, 0))]), (cord, cords), (leaf, leaves)])


SHADES = {"black_metal_dome": ((0.02, 0.02, 0.022), 0.35, 1.0), "white_enamel_dome": ((0.9, 0.9, 0.88), 0.2, 0.0),
          "brass_dome": ((0.62, 0.45, 0.18), 0.25, 1.0), "copper_dome": ((0.7, 0.35, 0.2), 0.25, 1.0),
          "glass_globe": ((0.95, 0.95, 0.92), 0.05, 0.0), "fabric_drum": ((0.85, 0.82, 0.75), 0.9, 0.0), "bare_bulb": None}


class DomePendantFactory:
    """A café pendant in the reference's shade (style evals: '15 copper domes where the ref has black enamel'): a cord from the
    ceiling, a dome / globe / drum / bare-bulb head, a glowing bulb. Origin at the ceiling point; `drop` metres of cord."""
    def __init__(self, seed, shade="black_metal_dome", drop=0.9):
        self.shade, self.drop = shade, drop

    def spawn_asset(self, i):
        z = -self.drop
        cord = _flat("ir_cord_black", (0.02, 0.02, 0.02), 0.6)
        bulb = _flat("ir_bulb_warm", (1.0, 0.85, 0.6), 0.3)
        bulb.node_tree.nodes["Principled BSDF"].inputs["Emission Color"].default_value = (1.0, 0.75, 0.45, 1)
        bulb.node_tree.nodes["Principled BSDF"].inputs["Emission Strength"].default_value = 2.5   # 6 blew out the shade undersides
        groups = [(cord, [("cyl", (0, 0, z / 2), (0.004, 0.004, abs(z)), (0, 0, 0)), ("cyl", (0, 0, -0.01), (0.04, 0.04, 0.02), (0, 0, 0))])]
        spec = SHADES.get(self.shade)
        if self.shade == "glass_globe":
            groups.append((_flat("ir_globe_glass", spec[0], spec[1], transmission=0.9), [("sph", (0, 0, z - 0.12), (0.13, 0.13, 0.13), (0, 0, 0))]))
        elif self.shade == "fabric_drum":
            groups.append((_flat("ir_drum_fabric", spec[0], spec[1], transmission=0.3), [("cyl", (0, 0, z - 0.1), (0.22, 0.22, 0.2), (0, 0, 0))]))
        elif spec is not None:                                    # domes: a wide shallow cone with a neck
            m = _flat(f"ir_shade_{self.shade}", *spec)
            # a bowl, not a cone (café M: 'the pendants are cones'): a rounded cap over a short flared skirt
            groups.append((m, [("cyl", (0, 0, z - 0.03), (0.03, 0.03, 0.06), (0, 0, 0)), ("sph", (0, 0, z - 0.1), (0.15, 0.15, 0.08), (0, 0, 0)),
                               ("cyl", (0, 0, z - 0.15), (0.2, 0.15, 0.08), (0, 0, 0))]))
        groups.append((bulb, [("sph", (0, 0, z - 0.2 if spec is not None and self.shade.endswith("dome") else z - 0.12), (0.035, 0.035, 0.05), (0, 0, 0))]))
        o = _prims(f"DomePendantFactory({i}).spawn_asset({i})", groups)
        if spec is not None:                                      # G r42 'faceted shades': the shade's cone skirt was flat-shaded (20 segments); smooth the shade slot (slot 1)
            for p_ in o.data.polygons:
                if p_.material_index == 1:
                    p_.use_smooth = True
        return o


class OliveTreeFactory:
    """A potted olive tree, 1.4-1.9 m: a terracotta or stone pot, a slim twisting trunk, clusters of grey-green leaf masses (floral / nordic
    refs: olive trees by the windows; Infinigen plants take minutes each)."""
    def __init__(self, seed):
        r = random.Random(seed); self.r = r; self.h = r.uniform(1.4, 1.9); self.seed = seed
        self.pot = r.choice(((0.6, 0.35, 0.22), (0.55, 0.53, 0.5), (0.12, 0.12, 0.12)))

    def _from_library(self, i):
        """A potted plant Infinigen grew offline (plant_gen.py): 'Infinigen makes plants well' (user 2026-10-17); growing one in the
        activity pass takes minutes and sometimes crashes Blender, so the pass appends a finished one. None when there is no library."""
        if STYLE.get("floor_plant_style") == "hssd":                                  # atrium lobby: HSSD scanned potted trees (ficus / schefflera / banana / dracaena ...), base on z = 0
            try:
                import sys as _sys
                if "/jarvis/project/robomituba/tools/infinigen" not in _sys.path:
                    _sys.path.insert(0, "/jarvis/project/robomituba/tools/infinigen")
                import abo_assets, asset_pools
                from mathutils import Matrix as _M
                pool_ = [e_ for e_ in asset_pools.pool("tall_plant") if e_["triangles"] <= 45000 and "banana" not in e_["name"].lower() and 1.3 <= e_["extent_m"][1] <= 2.4]
                if pool_:
                    rr_ = random.Random(self.seed * 7 + i)
                    o_ = abo_assets._import(abo_assets.pick(rr_, pool_), "HssdPlant")
                    if not o_.data.get("ir_base0"):
                        zs_ = [v_.co.z for v_ in o_.data.vertices]; xs_ = [v_.co.x for v_ in o_.data.vertices]; ys_ = [v_.co.y for v_ in o_.data.vertices]
                        o_.data.transform(_M.Translation((-(min(xs_) + max(xs_)) / 2, -(min(ys_) + max(ys_)) / 2, -min(zs_)))); o_.data["ir_base0"] = 1
                    hl_ = [float(v_) for v_ in (os.environ.get("ROOM_HSSD_PLANT_H") or "1.5,2.1").split(",")]; k_ = rr_.uniform(hl_[0], hl_[1]) / max(max(v_.co.z for v_ in o_.data.vertices), 0.3); o_.scale = (k_, k_, k_)
                    return o_
            except Exception as ex_:                                                # noqa: BLE001 -- the library plants below still work
                print(f"[plant] hssd skipped: {ex_!r}"[:140], flush=True)
        if STYLE.get("floor_plant_style") in ("library_v2", "infinigen"):             # data/plant_library_v2 (plant_lib2.py): whole-species pool, pot + scale there; falls through to the v1 library when it is missing
            from room_planner import plant_lib2 as _pl2
            p_ = _pl2.plant("floor", self.seed, i, h=min(self.h, 1.7), pot_rgb=self.pot) if _pl2.available() and SURFACE_DETAIL else None
            if p_ is not None:
                return p_
        files = sorted(f_ for f_ in PLANT_LIB.glob("plant_*.blend") if f_.stem[6:] not in (STYLE.get("plant_library_skip") or ())) if SURFACE_DETAIL else []     # kit plant_library_skip=["002", ...]: the spiky flower-stalk plants (O2 AST-01)
        if not files:
            return None
        f = files[(self.seed * 7 + i) % len(files)]
        try:
            with bpy.data.libraries.load(str(f), link=False) as (src, dst):
                dst.objects = list(src.objects)
            o = dst.objects[0]
            bpy.context.scene.collection.objects.link(o)
            co = [v.co for v in o.data.vertices]
            top = max(c.z for c in co); wide = max(max(c.x for c in co) - min(c.x for c in co), max(c.y for c in co) - min(c.y for c in co))
            sc = min((min(self.h, 1.6) - 0.4) / max(top, 1e-3), 0.9 / max(wide, 1e-3))   # a plant 1.0-1.2 m over a 0.4 m pot, under 0.9 m wide
            zmin = min(c.z for c in co); low = [c for c in co if c.z < zmin + 0.1 * max(top - zmin, 1e-3)]          # the stem base, not the bbox centre: a plant grown off-centre stood beside its pot (B r25 / O2 r8 LAY-02)
            bx, by = (sum(c.x for c in low) / len(low), sum(c.y for c in low) / len(low)) if low else (0.0, 0.0)
            o.scale = (sc, sc, sc); o.location = (-bx * sc, -by * sc, 0.36 - min(zmin, 0.0) * sc * 0.0)
            pot = _flat(f"ir_pot_{int(self.pot[0] * 100)}", self.pot, 0.8)
            base = _prims(f"OliveTreeFactory({i}).spawn_asset({i})", [(pot, [("cyl", (0, 0, 0.2), (0.17, 0.22, 0.4), (0, 0, 0))])])
            return _join_cloth(base, [o])
        except Exception as e:                                   # noqa: BLE001
            print(f"[proc_assets] plant library {f.name}: {e!r}"[:200])
            return None

    def spawn_asset(self, i):
        lib = self._from_library(i)
        if lib is not None:
            return lib
        r, h = self.r, self.h
        pot = _flat(f"ir_pot_{int(self.pot[0] * 100)}", self.pot, 0.8); bark = _flat("ir_bark", (0.18, 0.15, 0.12), 0.9)
        leaf = _flat("ir_olive_leaf", (0.22, 0.28, 0.18), 0.7)
        trunk, masses = [], []
        x = y = 0.0
        from mathutils import Vector
        n_seg = 6
        for k in range(n_seg):                                  # a slightly crooked trunk: tilted segments that meet end to end
            # (flat-tilted cylinders shifted sideways left 'a staircase trunk', user mark B r12 2026-10-17)
            z0 = 0.4 + k * (h - 0.9) / n_seg; dz = (h - 0.9) / n_seg; dx, dy = r.uniform(-0.03, 0.03), r.uniform(-0.03, 0.03)
            d = Vector((dx, dy, dz)); rot = Vector((0, 0, 1)).rotation_difference(d.normalized()).to_euler()
            trunk.append(("cyl", (x + dx / 2, y + dy / 2, z0 + dz / 2), (0.026 - 0.0015 * k, 0.026 - 0.0015 * (k + 1), d.length + 0.012), tuple(rot)))
            x += dx; y += dy
        # branches out of the trunk top, each ending in a cloud of small leaves; 7-11 big ellipsoids read as 'low-poly lollipop
        # blobs' in three style evals (cafe G)
        for k in range(r.randint(5, 8)):
            a, el = r.uniform(0, 6.28), r.uniform(0.35, 1.0)
            Lb = r.uniform(0.25, 0.45)
            tip = (x + Lb * math.cos(el) * math.cos(a), y + Lb * math.cos(el) * math.sin(a), h - 0.5 + Lb * math.sin(el))
            mid = ((x + tip[0]) / 2, (y + tip[1]) / 2, (h - 0.5 + tip[2]) / 2)
            trunk.append(("cyl", mid, (0.012, 0.008, Lb), (0, math.pi / 2 - el, a)))
            for _ in range(r.randint(28, 40)):
                q = (tip[0] + r.gauss(0, 0.09), tip[1] + r.gauss(0, 0.09), tip[2] + r.gauss(0, 0.07))
                masses.append(("sph", q, (0.035, 0.011, 0.004), (r.uniform(-1.2, 1.2), r.uniform(-1.2, 1.2), r.uniform(0, 6.28))))
        return _prims(f"OliveTreeFactory({i}).spawn_asset({i})",
                      [(pot, [("cyl", (0, 0, 0.2), (0.17, 0.22, 0.4), (0, 0, 0))]), (bark, trunk), (leaf, masses)])


class ChandelierFactory:
    """A crystal / brass chandelier (origin at the top): a ring of 6-10 arms with glowing bulbs and hanging crystal drops."""
    def __init__(self, seed):
        r = random.Random(seed); self.n = r.choice((6, 8, 10)); self.R = r.uniform(0.3, 0.45)

    def spawn_asset(self, i):
        n, R = self.n, self.R
        brass = _flat("ir_sconce_metal", (0.55, 0.38, 0.12), 0.3, 1.0); crystal = _flat("ir_crystal", (0.95, 0.95, 1.0), 0.02, transmission=1.0)
        bulb = _flat("ir_chandelier_bulb", (1.0, 0.85, 0.6), 0.3)
        bn = bulb.node_tree.nodes["Principled BSDF"]; bn.inputs["Emission Color"].default_value = (1.0, 0.72, 0.38, 1); bn.inputs["Emission Strength"].default_value = 18.0   # lit candle bulbs (S10: the chandelier is the room's focal glow)
        b = bulb.node_tree.nodes["Principled BSDF"]
        b.inputs["Emission Color"].default_value = (1.0, 0.62, 0.3, 1); b.inputs["Emission Strength"].default_value = 30.0
        arms, bulbs, drops = [("cyl", (0, 0, -0.25), (0.015, 0.015, 0.5), (0, 0, 0)), ("cyl", (0, 0, -0.5), (R, R, 0.02), (0, 0, 0))], [], []
        for k in range(n):
            a = 2 * math.pi * k / n
            x, y = R * math.cos(a), R * math.sin(a)
            arms.append(("cyl", (x / 2, y / 2, -0.5), (0.008, 0.008, R), (math.pi / 2, 0, a + math.pi / 2)))
            arms.append(("cyl", (x, y, -0.47), (0.018, 0.012, 0.05), (0, 0, 0)))          # candle cup
            bulbs.append(("sph", (x, y, -0.43), (0.012, 0.012, 0.03), (0, 0, 0)))          # candle-flame bulb (style eval: 'white globes')
            for j in range(5):                                                           # strands of crystal drops
                t = (k + j / 5) * 2 * math.pi / n
                drops.append(("sph", (R * 0.85 * math.cos(t), R * 0.85 * math.sin(t), -0.56 - 0.035 * (j % 3)), (0.008, 0.008, 0.018), (0, 0, 0)))
        drops += [("sph", (0, 0, -0.62 - 0.04 * j), (0.02 - 0.003 * j, 0.02 - 0.003 * j, 0.03), (0, 0, 0)) for j in range(4)]
        return _prims(f"ChandelierFactory({i}).spawn_asset({i})", [(brass, arms), (bulb, bulbs), (crystal, drops)])


class EspressoMachineFactory:
    """Two-group espresso machine (front +X): steel body, black top tray, two group heads, steam wand."""
    def __init__(self, seed):
        self.seed = seed

    def spawn_asset(self, i):
        # readable from the customer side too (cafe r4/r5: its plain back read as 'an oversized stainless cube', 2 of 3): a rounded
        # body, coloured side panels, a cup-warmer rail with white cups on top, group heads and portafilters on the barista side
        r = random.Random(self.seed)
        steel = _flat("ir_steel", (0.62, 0.62, 0.64), 0.2, 1.0); black = _flat("ir_black_metal", (0.03, 0.03, 0.03), 0.4, 1.0)
        if STYLE.get("espresso_rgb"):                            # kit: a plain painted machine (the scanned-steel body read as a blotchy stone blob at 1 m, market M r6)
            steel = _flat("ir_late_espresso_body", tuple(STYLE["espresso_rgb"]), 0.35, 0.3)
        side = steel if STYLE.get("espresso_finish") == "steel" else _flat(f"ir_espresso_side_{self.seed % 3}", r.choice(((0.45, 0.05, 0.04), (0.04, 0.04, 0.045), (0.8, 0.76, 0.66))), 0.3, 0.3)   # kit: stainless sides
        cup = _flat("ir_plate_white", (0.9, 0.9, 0.88), 0.25)
        cups = [("cyl", (-0.12 + 0.12 * (k // 4), -0.24 + 0.16 * (k % 4), 0.475), (0.035, 0.03, 0.065), (0, 0, 0)) for k in range(8)]
        return _prims(f"EspressoMachineFactory({i}).spawn_asset({i})",
                      [(steel, [("rbox", (0, 0, 0.22), (0.46, 0.6, 0.4), (0, 0, 0)),
                                ("box", (0, 0, 0.44), (0.42, 0.62, 0.012), (0, 0, 0)),               # cup-warmer tray
                                ("cyl", (0.27, -0.15, 0.24), (0.035, 0.035, 0.06), (0, math.pi / 2, 0)),
                                ("cyl", (0.27, 0.15, 0.24), (0.035, 0.035, 0.06), (0, math.pi / 2, 0)),
                                ("cyl", (0.27, 0.3, 0.3), (0.006, 0.006, 0.2), (0, 0, 0))]),       # steam wand
                       (side, [("box", (0, sy * 0.305, 0.22), (0.44, 0.012, 0.36), (0, 0, 0)) for sy in (1, -1)]),
                       (black, [("box", (0.3, sy * 0.15, 0.2), (0.12, 0.03, 0.02), (0, 0, 0)) for sy in (1, -1)] +   # portafilter handles
                               [("box", (0.24, 0, 0.03), (0.1, 0.6, 0.05), (0, 0, 0))]),                     # drip tray
                       (cup, cups)])


class CakeDomeFactory:
    """A cake under a glass dome on a stand (domes read as glass; the GT glass mask covers them)."""
    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        import bmesh
        r = self.r
        k = STYLE.get("dome_scale") or 1.0                       # baked into the geometry: the activity placer rebuilds matrix_world from a rotation and drops any object scale (S8 v12)
        cake = _flat(f"ir_cake_{i % 4}", [(0.55, 0.35, 0.2), (0.85, 0.75, 0.6), (0.4, 0.2, 0.15), (0.9, 0.6, 0.65)][i % 4] if not STYLE.get("cake_no_dome") else (0.86, 0.74, 0.55), 0.85 if STYLE.get("cake_no_dome") else 0.7)
        plate = _flat("ir_plate_white", (0.9, 0.9, 0.88), 0.25)
        glass = _flat("ir_dome_glass", (0.95, 0.95, 0.95), 0.02, transmission=1.0)
        o = _parts_object(f"CakeDomeFactory({i}).spawn_asset({i})",
                          [(plate, [(0, 0, 0.05 * k, 0.08 * k, 0.08 * k, 0.1 * k), (0, 0, 0.105 * k, 0.3 * k, 0.3 * k, 0.01 * k)]),
                           (cake, [(0, 0, 0.16 * k, 0.2 * k, 0.2 * k, r.uniform(0.07, 0.12) * k)])])
        if STYLE.get("cake_no_dome"):                                # kit: an open cake stand (the transmission dome rendered as a torn red slab at 1.6 m, market M r5)
            return o
        bm = bmesh.new(); bmesh.ops.create_uvsphere(bm, u_segments=24, v_segments=12, radius=0.15 * k)
        bmesh.ops.delete(bm, geom=[v for v in bm.verts if v.co.z < -0.001], context="VERTS")
        bmesh.ops.translate(bm, vec=(0, 0, 0.11 * k), verts=bm.verts)
        me = bpy.data.meshes.new(f"dome{i}"); bm.to_mesh(me); bm.free(); me.materials.append(glass)
        d = bpy.data.objects.new(f"dome{i}", me); bpy.context.scene.collection.objects.link(d); d.parent = o
        return o


class BackBarShelfFactory:
    """Open wall shelving behind the counter (front +X): 3-4 boards 0.28 m deep on a frame, 1.6-2.6 m long, 0.9-2.2 m high zone. FULL (set by realize for a layout item whose note says 'full-height' / 'floor-standing'): a
    floor-to-2.2 m unit, solid sides and back, 5 shelves from 0.12 m, a plinth, no thin rods (S31 r13: the wall-hung design stood free in the room as a box on two rods)."""
    FULL = False

    def __init__(self, seed):
        r = random.Random(seed)
        self.L = r.uniform(1.6, 2.6); self.levels = r.choice((3, 4))
        self.wood = STYLE.get("backbar") or r.choice(("walnut_slat", "oak_slat", "matte_black"))

    def spawn_asset(self, i):
        L, D = self.L, 0.28
        wood = _flat("ir_backbar_paint", tuple(STYLE["backbar_rgb"]), 0.4) if STYLE.get("backbar_rgb") else _flat(f"ir_counter_{self.wood}", *COUNTER_FRONTS[self.wood]); metal = _flat("ir_black_metal", (0.03, 0.03, 0.03), 0.4, 1.0)   # kit backbar_rgb: painted (white) shelving
        zs = [1.15 + k * (1.05 / (self.levels - 1)) for k in range(self.levels)]
        if BackBarShelfFactory.FULL:                                                          # full-height floor-standing unit
            zs = [0.14, 0.64, 1.14, 1.64, 2.14]
            groups = [(wood, [(0, 0, z, D, L, 0.03) for z in zs] + [(-D / 2 + 0.006, 0, 1.1, 0.012, L, 2.2)] + [(0, sx * (L / 2 - 0.015), 1.1, D, 0.03, 2.2) for sx in (-1, 1)]),
                      (metal, [(0, 0, 0.05, D - 0.02, L - 0.02, 0.1)])]
            if STYLE.get("mood") in ("warm_evening", "dark_moody"):
                led = _flat("ir_led_warm", (1.0, 0.75, 0.45), 0.3); b = led.node_tree.nodes["Principled BSDF"]
                b.inputs["Emission Color"].default_value = (1.0, 0.72, 0.42, 1); b.inputs["Emission Strength"].default_value = 6.0
                groups.append((led, [(D / 2 - 0.04, 0, z - 0.02, 0.015, L - 0.08, 0.008) for z in zs[1:]]))
            return _parts_object(f"BackBarShelfFactory({i}).spawn_asset({i})", groups)
        if STYLE.get("backbar_chalkboard"):                      # kit backbar_chalkboard (H r71: 'a large chalkboard above the counter in place of the white cup shelving'): two low shelves and a framed menu board above
            zs = [0.95, 1.3]
            bk = _flat("ir_chalk_black", (0.05, 0.055, 0.05), 0.85); fr_ = _flat("ir_chalk_frame", (0.55, 0.38, 0.2), 0.5, wood=True)
            cm = sorted((PRINT_ROOT.glob("chalk_menu_*.png")))
            bw_, bh_ = L, L / 2.0
            while bh_ > 1.0:
                bh_ *= 0.9
            bz = 1.5 + bh_ / 2
            frame = [(-D / 2 + 0.012, 0, bz + bh_ / 2 + 0.03, 0.03, bw_ + 0.08, 0.06), (-D / 2 + 0.012, 0, bz - bh_ / 2 - 0.03, 0.03, bw_ + 0.08, 0.06)] + [(-D / 2 + 0.012, sy * (bw_ / 2 + 0.03), bz, 0.03, 0.06, bh_ + 0.12) for sy in (1, -1)]
            gr = [(wood, [(0, 0, z, D, L, 0.03) for z in zs] + [(-D / 2 + 0.006, 0, 1.0, 0.012, L, 0.7)] + [(0, sx * (L / 2 - 0.015), 1.0, D, 0.03, 0.7) for sx in (-1, 1)]), (fr_, frame)]
            if cm:
                gr.append((_printed(cm[0], (0.9, 0.9, 0.9), 0.85), [(-D / 2 + 0.02, 0, bz, 0.004, bw_, bh_)]))
            else:
                gr.append((bk, [(-D / 2 + 0.02, 0, bz, 0.004, bw_, bh_)]))
            return _parts_object(f"BackBarShelfFactory({i}).spawn_asset({i})", gr)
        groups = [(wood, [(0, 0, z, D, L, 0.03) for z in zs] + [(-D / 2 + 0.006, 0, 1.6, 0.012, L, 1.0)] +   # back panel and end
                         [(0, sx * (L / 2 - 0.015), 1.6, D, 0.03, 1.0) for sx in (-1, 1)]),               # uprights: bare boards
                  (metal, [(-D / 2 + 0.01, sx * (L / 2 - 0.03), 1.1, 0.02, 0.02, 2.2) for sx in (-1, 1)])]   # read as floating (shop r5)
        if STYLE.get("mood") in ("warm_evening", "dark_moody"):   # glowing under-shelf strips (cafe refs: the back bar is the warm light source)
            led = _flat("ir_led_warm", (1.0, 0.75, 0.45), 0.3)
            b = led.node_tree.nodes["Principled BSDF"]
            b.inputs["Emission Color"].default_value = (1.0, 0.72, 0.42, 1); b.inputs["Emission Strength"].default_value = 6.0
            groups.append((led, [(D / 2 - 0.04, 0, z - 0.02, 0.015, L - 0.08, 0.008) for z in zs]))
        return _parts_object(f"BackBarShelfFactory({i}).spawn_asset({i})", groups)


class WindowBarFactory:
    """A ledge along shop-front glass (front +X): 0.4 m deep wooden top at 1.05 m on two steel legs, 1.6-3.0 m long."""
    def __init__(self, seed):
        self.L = random.Random(seed).uniform(*STYLE["window_bar_len_m"]) if STYLE.get("window_bar_len_m") else random.Random(seed).uniform(1.6, 3.0)      # kit window_bar_len_m=[min,max]: one long ledge along the whole glazed front

    def spawn_asset(self, i):
        L = self.L
        wood = _flat("ir_counter_top_butcher_block", *COUNTER_TOPS["butcher_block"], wood=True); metal = _flat("ir_black_metal", (0.03, 0.03, 0.03), 0.4, 1.0)
        return _parts_object(f"WindowBarFactory({i}).spawn_asset({i})",
                             [(wood, [(0, 0, 1.03, 0.4, L, 0.04)]),
                              (metal, [(0, sx * (L / 2 - 0.15), 0.5, 0.04, 0.04, 1.0) for sx in (-1, 1)])])


# ---- retail -------------------------------------------------------------------------------------------------------------------------
HEADER_COLOURS = [(0.75, 0.08, 0.06), (0.05, 0.3, 0.6), (0.08, 0.45, 0.2), (0.85, 0.55, 0.05), (0.45, 0.1, 0.45)]


class PlasticBinFactory:
    """An open-front plastic picking bin (front +X) in blue, grey, red or yellow, with a label slot; warehouse r5: 'every box is the
    same tan cardboard -- a staged product shot'."""
    def __init__(self, seed):
        r = random.Random(seed)
        # mid-saturation blue / charcoal / green / red: muted (wh r13: 'toy-bright') but not the cardboard's beige -- 47 bins in packing
        # r18 at the old pale greys and beige read as boxes, 3 of 3 calls: 'every shelf the same pale cream boxes'
        # deeper still: the auto-exposed packing room lifted these to 'pastel salmon, mint, sky blue -- a toy store' (wh r19, 3 of 3)
        self.c = r.choice(((0.01, 0.05, 0.22), (0.01, 0.05, 0.22), (0.05, 0.055, 0.06), (0.45, 0.25, 0.0), (0.22, 0.015, 0.01)))
        self.w, self.d, self.h = r.choice(((0.2, 0.35, 0.15), (0.3, 0.45, 0.2), (0.4, 0.6, 0.25)))

    def spawn_asset(self, i):
        w, d, h = self.w, self.d, self.h
        m = _flat(f"ir_bin_{int(self.c[0] * 100)}_{int(self.c[2] * 100)}", self.c, 0.5); lab = _flat("ir_paper", (0.93, 0.93, 0.9), 0.7)
        t = 0.008
        return _parts_object(f"PlasticBinFactory({i}).spawn_asset({i})",
                             [(m, [(0, 0, t / 2, d, w, t), (-d / 2, 0, h / 2, t, w, h), (0, w / 2, h / 2, d, t, h), (0, -w / 2, h / 2, d, t, h),
                                   (d / 2, 0, h * 0.3, t, w, h * 0.6)]),
                              (lab, [(d / 2 + 0.002, 0, h * 0.35, 0.002, w * 0.5, h * 0.18)])])


class StepLadderFactory:
    """An A-frame aluminium step ladder (front +X), 1.2-1.6 m, standing open (ABO 'ladder' drew ladder shelves and ladder-back chairs:
    warehouse r6 'a white bookcase and spindle dining chairs')."""
    def __init__(self, seed):
        self.h = random.Random(seed).choice((1.2, 1.4, 1.6))

    def spawn_asset(self, i):
        h = self.h; alu = _flat("ir_wh_alu", (0.8, 0.8, 0.82), 0.3, 1.0); grip = _flat("ir_ladder_grip", (0.8, 0.15, 0.05), 0.6)
        a = 0.22                                                  # leg splay (rad)
        legs = [("box", (sx * math.sin(a) * h / 2, sy * 0.2, h / 2 * math.cos(a)), (0.04, 0.025, h), (0, sx * -a, 0)) for sx in (1, -1) for sy in (1, -1)]
        steps = [("box", (math.sin(a) * z, 0, z), (0.1, 0.42, 0.02), (0, 0, 0)) for z in [h * (k + 1) / 5 for k in range(4)]]
        return _prims(f"StepLadderFactory({i}).spawn_asset({i})",
                      [(alu, legs + steps), (grip, [("box", (0, 0, h * math.cos(a) + 0.02), (0.2, 0.44, 0.05), (0, 0, 0))])])


class OpenBoxFactory:
    """A carton being packed: open, four flaps folded out, crumpled kraft paper inside (warehouse r7: 'no box being packed')."""
    def __init__(self, seed):
        r = random.Random(seed); self.s = (r.uniform(0.25, 0.45), r.uniform(0.2, 0.35), r.uniform(0.15, 0.3)); self.r = r

    def spawn_asset(self, i):
        x, y, z = self.s; t = 0.005; card = cardboard(); kraft = _flat("ir_kraft", (0.55, 0.42, 0.28), 0.9)
        walls = [("box", (0, 0, t / 2), (x, y, t), (0, 0, 0)), ("box", (x / 2, 0, z / 2), (t, y, z), (0, 0, 0)), ("box", (-x / 2, 0, z / 2), (t, y, z), (0, 0, 0)),
                 ("box", (0, y / 2, z / 2), (x, t, z), (0, 0, 0)), ("box", (0, -y / 2, z / 2), (x, t, z), (0, 0, 0))]
        flaps = [("box", (sx * (x / 2 + y * 0.22), 0, z + 0.02), (y * 0.45, y, t), (0, sx * -0.35, 0)) for sx in (1, -1)]
        paper = [("sph", (self.r.uniform(-x / 4, x / 4), self.r.uniform(-y / 4, y / 4), z * 0.75), (x * 0.2, y * 0.2, z * 0.18), (0, 0, k)) for k in range(3)]
        return _prims(f"OpenBoxFactory({i}).spawn_asset({i})", [(card, walls + flaps), (kraft, paper)])


class TapeGunFactory:
    """A packing-tape dispenser gun with a roll of brown tape."""
    def __init__(self, seed):
        self.c = random.Random(seed).choice(((0.9, 0.7, 0.05), (0.08, 0.08, 0.08), (0.4, 0.42, 0.45)))   # industrial, not salmon (r17)

    def spawn_asset(self, i):
        body = _flat(f"ir_tapegun_{int(self.c[0] * 100)}", self.c, 0.4); tape = _flat("ir_tape", (0.6, 0.42, 0.22), 0.3)
        return _prims(f"TapeGunFactory({i}).spawn_asset({i})",
                      [(body, [("box", (0, 0, 0.06), (0.04, 0.2, 0.03), (0, 0, 0)), ("box", (0, -0.08, 0.03), (0.035, 0.03, 0.08), (0.3, 0, 0))]),
                       (tape, [("cyl", (0, 0.04, 0.09), (0.05, 0.05, 0.05), (0, math.pi / 2, 0))])])


class KraftRollFactory:
    """A roll of kraft packing paper lying on the bench."""
    def __init__(self, seed):
        self.L = random.Random(seed).uniform(0.5, 0.8)

    def spawn_asset(self, i):
        kraft = _flat("ir_kraft", (0.55, 0.42, 0.28), 0.9)
        return _prims(f"KraftRollFactory({i}).spawn_asset({i})", [(kraft, [("cyl", (0, 0, 0.06), (0.06, 0.06, self.L), (math.pi / 2, 0, 0))])])


class HandTruckFactory:
    """A two-wheel hand truck (front +X) standing upright on its toe plate, sometimes with a carton on it (warehouse r9: 'no hand truck,
    ladder or tape -- a showroom')."""
    def __init__(self, seed):
        r = random.Random(seed); self.c = r.choice(((0.85, 0.1, 0.05), (0.15, 0.3, 0.6), (0.2, 0.2, 0.2))); self.box = r.random() < 0.5

    def spawn_asset(self, i):
        frame = _flat(f"ir_truck_{int(self.c[0] * 100)}", self.c, 0.4, 0.5); rub = _flat("ir_black_metal", (0.03, 0.03, 0.03), 0.4, 1.0)
        rails = [("cyl", (-0.08, sy * 0.18, 0.62), (0.015, 0.015, 1.2), (0, -0.12, 0)) for sy in (1, -1)]
        groups = [(frame, rails + [("box", (-0.08 - 0.07 * k, 0, 0.3 + 0.3 * k), (0.02, 0.36, 0.02), (0, 0, 0)) for k in range(3)] +
                   [("box", (0.08, 0, 0.02), (0.2, 0.36, 0.02), (0, 0, 0))]),
                  (rub, [("cyl", (-0.1, sy * 0.24, 0.12), (0.12, 0.12, 0.06), (math.pi / 2, 0, 0)) for sy in (1, -1)])]
        if self.box:
            groups.append((cardboard(), [("box", (0.08, 0, 0.22), (0.3, 0.32, 0.38), (0, 0, 0))]))
        return _prims(f"HandTruckFactory({i}).spawn_asset({i})", groups)


class RecycleBinsFactory:
    """An office recycling station (front +X): three lidded bins in blue / green / grey with label strips (pantry r21: 'the back and right
    walls have nothing: no recycling bins, no noticeboard')."""
    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        groups = []
        for k, c in enumerate(((0.1, 0.3, 0.65), (0.15, 0.5, 0.2), (0.35, 0.36, 0.38))):
            y = (k - 1) * 0.38
            groups.append((_flat(f"ir_bin_{k}", c, 0.5), [("box", (0, y, 0.38), (0.4, 0.34, 0.76), (0, 0, 0))]))
            groups.append((_flat("ir_bin_lid", (0.12, 0.12, 0.12), 0.5), [("box", (0, y, 0.775), (0.42, 0.36, 0.03), (0, 0, 0))]))
            groups.append((_flat("ir_paper", (0.93, 0.93, 0.9), 0.7), [("box", (0.201, y, 0.62), (0.002, 0.2, 0.08), (0, 0, 0))]))
        return _prims(f"RecycleBinsFactory({i}).spawn_asset({i})", groups)


class ClinicWallItemFactory:
    """Wall-mounted clinic fixtures (front +X, origin at the bottom of the back plate), the signs of use a wide shot can see (clinic
    r17: signs of use median 4-5 with props only on worktops): an eye chart, an anatomy/notice poster, a three-box glove holder, a
    yellow sharps bin, a paper-towel dispenser, a sanitizer dispenser."""
    KINDS = ("eye_chart", "clinic_poster", "glove_holder", "sharps_bin", "towel_dispenser", "wall_sanitizer", "wall_clock", "brochure_rack",
             "grab_bar", "hand_dryer", "toilet_roll", "waste_bin", "coat_hooks", "baby_change", "door_sign", "diagnostic_set",
             "cleaning_kit", "roll_shelf", "handrail")

    def __init__(self, seed, kind="clinic_poster", length=1.0):
        self.kind, self.r, self.length = kind, random.Random(seed), length

    def spawn_asset(self, i):
        r, k = self.r, self.kind
        white = _flat("ir_ac_white", (0.86, 0.86, 0.85), 0.4); ink = _flat("ir_ink", (0.05, 0.05, 0.06), 0.6)
        if k in ("eye_chart", "clinic_poster"):
            frame = _flat("ir_poster_frame", (0.75, 0.75, 0.76), 0.35, 0.8)
            W, H = (0.5, 0.75) if k == "eye_chart" else (0.6, 0.85)
            parts = [("box", (0.005, 0, H / 2), (0.01, W, H), (0, 0, 0))]
            if k == "eye_chart":                                 # rows of letters shrinking down the chart
                marks = [("box", (0.012, (j - (n - 1) / 2) * (0.36 / n), H - 0.1 - row * 0.085), (0.002, 0.36 / n * 0.6, 0.06 / (1 + row * 0.35)), (0, 0, 0))
                         for row in range(7) for n in [row + 1] for j in range(n)]
                return _prims(f"ClinicWallItemFactory({i}).spawn_asset({i})", [(frame, [("box", (0.004, 0, H / 2), (0.008, W + 0.03, H + 0.03), (0, 0, 0))]),
                                                                              (white, [("box", (0.009, 0, H / 2), (0.002, W, H), (0, 0, 0))]), (ink, marks)])
            pp = _pick_print(_poster_prefix(), i)
            if pp is not None:                                   # a printed poster / framed print / safety sign, at its own aspect
                im_ = bpy.data.images.load(str(pp), check_existing=True); asp = im_.size[0] / max(im_.size[1], 1)
                W, H = (0.9 * asp, 0.9) if asp < 1 else (0.9, 0.9 / asp)
                return _prims(f"ClinicWallItemFactory({i}).spawn_asset({i})", [(frame, [("box", (0.004, 0, H / 2), (0.008, W + 0.03, H + 0.03), (0, 0, 0))]),
                                                                              (_printed(pp, (0.9, 0.9, 0.9), 0.5), [("box", (0.009, 0, H / 2), (0.002, W, H), (0, 0, 0))])])
            col = _flat(f"ir_poster_{r.randrange(4)}", r.choice(((0.75, 0.3, 0.3), (0.3, 0.5, 0.7), (0.4, 0.6, 0.4), (0.85, 0.7, 0.4))), 0.6)
            lines = [("box", (0.012, 0, H - 0.3 - j * 0.05), (0.002, W * 0.75, 0.012), (0, 0, 0)) for j in range(8)]
            return _prims(f"ClinicWallItemFactory({i}).spawn_asset({i})", [(frame, [("box", (0.004, 0, H / 2), (0.008, W + 0.03, H + 0.03), (0, 0, 0))]),
                                                                          (white, [("box", (0.009, 0, H / 2), (0.002, W, H), (0, 0, 0))]),
                                                                          (col, [("sph", (0.012, 0, H - 0.15), (0.002, W * 0.25, 0.1), (0, 0, 0))]), (ink, lines)])
        if k == "handrail":                                      # a clinic corridor's wall rail, door to door: the posters and plates
            # alone read as 'four bare white walls' (floor F3 r19: corridor use 4, 3 of 3)
            L = self.length; wood = _flat("ir_rail_oak", (0.42, 0.28, 0.16), 0.45); steel = _flat("ir_chrome", (0.8, 0.8, 0.82), 0.15, 1.0)
            n = max(2, int(L / 1.0) + 1)
            brk = [("box", (0.035, -L / 2 + 0.08 + j * (L - 0.16) / (n - 1), 0.0), (0.07, 0.02, 0.03), (0, 0, 0)) for j in range(n)]
            return _prims(f"ClinicWallItemFactory({i}).spawn_asset({i})", [(wood, [("cyl", (0.075, 0, 0.0), (0.022, 0.022, L), (math.pi / 2, 0, 0))]),
                                                                          (steel, brk)])
        if k == "roll_shelf":                                    # spare toilet rolls on a small wall shelf: a restroom someone restocks
            # ('no spare paper rolls, nothing used', floors F3 r18 / H r26, 3 of 3) -- quieter than the mop kit, which read as clutter
            shelf = _flat("ir_ac_white", (0.86, 0.86, 0.85), 0.4); paper = _flat("ir_paper", (0.93, 0.93, 0.9), 0.7)
            rolls = [("cyl", (0.07, y, 0.035 + 0.055 + dz), (0.055, 0.055, 0.11), (0, 0, 0)) for y, dz in ((-0.12, 0), (0.0, 0), (0.12, 0), (-0.06, 0.11), (0.06, 0.11))]
            return _prims(f"ClinicWallItemFactory({i}).spawn_asset({i})", [(shelf, [("box", (0.07, 0, 0.0175), (0.14, 0.4, 0.035), (0, 0, 0)),
                                                                                    ("box", (0.005, 0, -0.05), (0.01, 0.4, 0.1), (0, 0, 0))]),
                                                                           (paper, rolls)])
        if k == "cleaning_kit":                                  # a restroom being looked after: a yellow mop bucket with its mop leant on
            # the wall and a wet-floor A-frame (floors H r19 / I r14: restroom signs of use 5-6, 'clinically bare', 3 of 3)
            yel = _flat("ir_janitor_yellow", (0.85, 0.65, 0.05), 0.45); grey = _flat("ir_mop_grey", (0.55, 0.55, 0.55), 0.9)
            pole = _flat("ir_mop_pole", (0.7, 0.72, 0.74), 0.3, 0.9); a_ = 0.2
            return _prims(f"ClinicWallItemFactory({i}).spawn_asset({i})", [
                (yel, [("box", (0.2, -0.15, 0.15), (0.3, 0.4, 0.3), (0, 0, 0)), ("box", (0.2, 0.0, 0.32), (0.3, 0.1, 0.04), (0, 0, 0)),
                       ("box", (0.24, 0.42, 0.3), (0.025, 0.32, 0.62), (0, a_, 0))]),   # ONE sign face leaning on a back leg: the two
                # A-frame leaves read as 'two wet-floor signs side by side' (floor H r25, 3 of 3)
                (_flat("ir_mop_pole", (0.7, 0.72, 0.74), 0.3, 0.9), [("box", (0.38, 0.42, 0.29), (0.015, 0.02, 0.58), (0, -0.4, 0))]),
                # the two leaves meet at the top: 0.24 m apart they read as two or three loose signs (floor E3 r13, 3 of 3)
                (grey, [("box", (0.2, -0.22, 0.31), (0.18, 0.18, 0.06), (0, 0, 0))]),
                # no mop pole: leant on the wall it read as 'a loose rod, debris' (floor F3 r16, 3 of 3)
                (_flat("ir_ink", (0.05, 0.05, 0.06), 0.6), [("box", (0.24 - 0.016, 0.42, 0.37), (0.002, 0.18, 0.14), (0, a_, 0))])])
        if k == "glove_holder":
            boxes = [(_flat(f"ir_glovebox_{j}", c, 0.6), [("box", (0.07, 0, 0.06 + j * 0.13), (0.12, 0.26, 0.11), (0, 0, 0))])
                     for j, c in enumerate(((0.3, 0.35, 0.75), (0.55, 0.3, 0.65), (0.85, 0.85, 0.88)))]
            return _prims(f"ClinicWallItemFactory({i}).spawn_asset({i})", [(white, [("box", (0.005, 0, 0.21), (0.01, 0.3, 0.42), (0, 0, 0))])] + boxes)
        if k == "sharps_bin":
            # red body on a grey wall bracket, white lid and label (clinic r19: the yellow box with a red cap read as a desk lamp, 2 of 3 calls)
            red = _flat("ir_sharps_red", (0.62, 0.06, 0.05), 0.35); lid = _flat("ir_sharps_lid", (0.9, 0.9, 0.88), 0.4)
            steel = _flat("ir_sharps_bracket", (0.55, 0.56, 0.58), 0.35, 1.0)
            return _prims(f"ClinicWallItemFactory({i}).spawn_asset({i})", [(steel, [("box", (0.006, 0, 0.17), (0.012, 0.2, 0.34), (0, 0, 0)),
                                                                                   ("box", (0.08, 0, 0.012), (0.15, 0.24, 0.012), (0, 0, 0))]),
                                                                          (red, [("box", (0.09, 0, 0.14), (0.15, 0.22, 0.24), (0, 0, 0))]),
                                                                          (lid, [("box", (0.09, 0, 0.275), (0.16, 0.23, 0.03), (0, 0, 0)),
                                                                                 ("box", (0.166, 0, 0.15), (0.002, 0.12, 0.08), (0, 0, 0))])])
        if k == "wall_clock":                                    # reception r22: 'no clock, no signage' (3 of 3)
            rim = _flat("ir_black_metal", (0.03, 0.03, 0.03), 0.4, 1.0)
            # the face sat inside the 4 cm rim (x 0.03 < 0.04) and rendered as 'a black disc with no clock face' (floor H r45, 3 of 3)
            hands = [("box", (0.047, 0, 0.18 + 0.05), (0.004, 0.012, 0.1), (0, 0, 0)), ("box", (0.047, 0.04, 0.18), (0.004, 0.08, 0.01), (0, 0, 0))]
            ticks = [("box", (0.045, math.sin(a_) * 0.145, 0.18 + math.cos(a_) * 0.145), (0.003, 0.012, 0.022), (a_, 0, 0))
                     for a_ in [j * math.pi / 6 for j in range(12)]]
            return _prims(f"ClinicWallItemFactory({i}).spawn_asset({i})", [(rim, [("cyl", (0.02, 0, 0.18), (0.18, 0.18, 0.04), (0, math.pi / 2, 0))] + hands + ticks),
                                                                          (white, [("cyl", (0.042, 0, 0.18), (0.165, 0.165, 0.004), (0, math.pi / 2, 0))])])
        if k == "brochure_rack":                                 # clear pockets with coloured leaflets (reception: 'no brochure rack')
            acr = _flat("ir_acrylic", (0.9, 0.92, 0.93), 0.1, transmission=0.8)
            cols = [_flat(f"ir_leaflet_{j}", c, 0.6) for j, c in enumerate(((0.15, 0.45, 0.7), (0.85, 0.85, 0.82), (0.2, 0.55, 0.35), (0.85, 0.5, 0.15)))]
            pockets = [("box", (0.05, -0.15 + (j % 3) * 0.15, 0.1 + (j // 3) * 0.22), (0.04, 0.13, 0.16), (0, 0, 0)) for j in range(6)]
            return _prims(f"ClinicWallItemFactory({i}).spawn_asset({i})", [(white, [("box", (0.005, 0, 0.3), (0.01, 0.48, 0.62), (0, 0, 0))]), (acr, pockets)] +
                          [(cols[j % 4], [("box", (0.045, -0.15 + (j % 3) * 0.15, 0.13 + (j // 3) * 0.22), (0.01, 0.1, 0.2), (0, 0, 0))]) for j in range(6)])
        if k == "grab_bar":                                      # restrooms read 'empty with a toilet in it' (floor D3 r7, 3 of 3)
            chrome = _flat("ir_chrome", (0.8, 0.8, 0.82), 0.15, 1.0)
            return _prims(f"ClinicWallItemFactory({i}).spawn_asset({i})", [(chrome, [
                ("cyl", (0.07, 0, 0.06), (0.018, 0.018, 0.75), (math.pi / 2, 0, 0)),
                ("box", (0.035, 0.35, 0.06), (0.07, 0.03, 0.03), (0, 0, 0)), ("box", (0.035, -0.35, 0.06), (0.07, 0.03, 0.03), (0, 0, 0))])])
        if k == "diagnostic_set":                                # wall BP gauge + otoscope/ophthalmoscope handles (floor D3 r9-r11, 3 of 3)
            grey = _flat("ir_diag_grey", (0.55, 0.57, 0.6), 0.4); blk = _flat("ir_black_plastic", (0.04, 0.04, 0.045), 0.5)
            cuff = _flat("ir_bp_cuff", (0.1, 0.18, 0.35), 0.7)
            return _prims(f"ClinicWallItemFactory({i}).spawn_asset({i})", [
                (grey, [("box", (0.01, 0, 0.22), (0.02, 0.42, 0.44), (0, 0, 0))]),
                (white, [("cyl", (0.03, -0.09, 0.32), (0.07, 0.07, 0.02), (0, math.pi / 2, 0))]),
                (blk, [("cyl", (0.045, 0.08, 0.28), (0.018, 0.018, 0.16), (0, 0, 0)), ("cyl", (0.045, 0.14, 0.28), (0.018, 0.018, 0.16), (0, 0, 0)),
                       ("box", (0.035, -0.09, 0.32), (0.004, 0.004, 0.05), (0, 0, 0.6))]),
                (cuff, [("rbox", (0.05, -0.09, 0.1), (0.06, 0.16, 0.12), (0, 0, 0))])])
        if k == "door_sign":                                     # a room plate beside each corridor door (floors D3/E3/F3: 'no room signs')
            plate = _flat("ir_door_sign", r.choice(((0.12, 0.3, 0.45), (0.2, 0.22, 0.25), (0.1, 0.4, 0.38))), 0.4)
            ink3 = _flat("ir_sign_ink", (0.95, 0.95, 0.93), 0.5)
            lines = [("box", (0.012, -0.08 + j * 0.04, 0.075), (0.002, 0.03, 0.035), (0, 0, 0)) for j in range(r.randint(3, 5))]
            return _prims(f"ClinicWallItemFactory({i}).spawn_asset({i})", [(plate, [("box", (0.005, 0, 0.075), (0.01, 0.3, 0.15), (0, 0, 0))]),
                                                                          (ink3, lines + [("box", (0.012, 0.09, 0.075), (0.002, 0.06, 0.06), (0, 0, 0))])])
        if k == "baby_change":                                   # a fold-down baby-change unit (floors D3/J: 'an oversized WC, nothing in use')
            grey = _flat("ir_babychange", (0.82, 0.84, 0.86), 0.4); ink2 = _flat("ir_sign_blue", (0.1, 0.3, 0.6), 0.5)
            return _prims(f"ClinicWallItemFactory({i}).spawn_asset({i})", [(grey, [("rbox", (0.06, 0, 0.27), (0.12, 0.86, 0.54), (0, 0, 0)),
                                                                                  ("box", (0.121, 0, 0.47), (0.004, 0.7, 0.03), (0, 0, 0))])])   # a
            # handle strip, no blue square: the sign read as 'a clinic wall unit' in café WCs (floor G r14, 3 of 3)
        if k == "coat_hooks":                                    # a changing room's hook rail with two jackets (floor F3 r7: 'no coat hooks')
            oak = _flat("ir_hook_board", (0.55, 0.42, 0.28), 0.5); chrome = _flat("ir_chrome", (0.8, 0.8, 0.82), 0.15, 1.0)
            jk = [_flat(f"ir_jacket_{j}", c, 0.8) for j, c in enumerate(((0.12, 0.16, 0.28), (0.45, 0.12, 0.1)))]
            hooks = [("box", (0.04, -0.36 + j * 0.24, 0.0), (0.06, 0.015, 0.015), (0, 0, 0)) for j in range(4)]
            return _prims(f"ClinicWallItemFactory({i}).spawn_asset({i})", [(oak, [("box", (0.01, 0, 0.02), (0.02, 0.9, 0.09), (0, 0, 0))]),
                (chrome, hooks), (jk[0], [("rbox", (0.09, -0.36, -0.38), (0.1, 0.42, 0.72), (0, 0, 0))]),
                (jk[1], [("rbox", (0.09, 0.12, -0.33), (0.1, 0.4, 0.62), (0, 0, 0))])])
        if k == "toilet_roll":                                   # restrooms: 'no toilet-roll holder, no bin' (floors C/D3/F3/H, 3 of 3 each)
            chrome = _flat("ir_chrome", (0.8, 0.8, 0.82), 0.15, 1.0); paper = _flat("ir_paper", (0.93, 0.93, 0.9), 0.7)
            return _prims(f"ClinicWallItemFactory({i}).spawn_asset({i})", [(chrome, [("box", (0.01, 0, 0.06), (0.02, 0.16, 0.08), (0, 0, 0)),
                                                                                    ("cyl", (0.07, 0, 0.04), (0.008, 0.008, 0.15), (math.pi / 2, 0, 0))]),
                                                                          (paper, [("cyl", (0.07, 0, 0.04), (0.055, 0.055, 0.1), (math.pi / 2, 0, 0))])])
        if k == "waste_bin":                                     # an open bin at the wall (z = 0) with used paper towels above its rim:
            # a closed pedal bin showed 'nothing in the bins, no sign of use' in every restroom (floors H/I/J r24-r40, 3 of 3 each)
            steel = _flat("ir_bin_steel", (0.62, 0.63, 0.64), 0.3, 1.0); blk = _flat("ir_black_plastic", (0.04, 0.04, 0.045), 0.5)
            paper = _flat("ir_paper", (0.93, 0.93, 0.9), 0.7)
            wads = [("sph", (0.16 + dx, dy, 0.42 + dz), (0.075, 0.065, 0.05), (0, 0, 0)) for dx, dy, dz in   # heaped over the rim:
                    ((0, 0, 0.03), (0.06, 0.05, 0.0), (-0.05, -0.06, 0.01), (0.04, -0.04, 0.07), (-0.06, 0.04, 0.05),   # smaller wads were a
                     (0.0, 0.07, 0.04), (-0.02, -0.01, 0.1), (0.07, -0.06, 0.03))]   # few pixels at 512 px, use 5-6 (floor H r41, 3 of 3)
            return _prims(f"ClinicWallItemFactory({i}).spawn_asset({i})", [(paper, wads), (steel, [("cyl", (0.16, 0, 0.21), (0.14, 0.14, 0.42), (0, 0, 0))]),
                                                                          (blk, [("box", (0.32, 0, 0.02), (0.06, 0.1, 0.02), (0, 0, 0)),
                                                                                 ("cyl", (0.16, 0, 0.01), (0.145, 0.145, 0.02), (0, 0, 0))])])
        if k == "hand_dryer":                                    # brushed steel: a white box on white tile was never seen (floor H r27, 3 of 3)
            steel = _flat("ir_dryer_steel", (0.6, 0.61, 0.63), 0.3, 1.0)
            return _prims(f"ClinicWallItemFactory({i}).spawn_asset({i})", [(steel, [("rbox", (0.1, 0, 0.17), (0.2, 0.3, 0.34), (0, 0, 0))]),
                                                                          (ink, [("box", (0.12, 0, 0.005), (0.08, 0.16, 0.02), (0, 0, 0))])])
        if k == "towel_dispenser":
            return _prims(f"ClinicWallItemFactory({i}).spawn_asset({i})", [(white, [("box", (0.06, 0, 0.18), (0.12, 0.28, 0.36), (0, 0, 0))]),
                                                                          (ink, [("box", (0.121, 0, 0.03), (0.002, 0.2, 0.01), (0, 0, 0))])])
        return _prims(f"ClinicWallItemFactory({i}).spawn_asset({i})", [(white, [("box", (0.05, 0, 0.12), (0.1, 0.11, 0.24), (0, 0, 0))]),
                                                                      (ink, [("box", (0.101, 0, 0.05), (0.002, 0.06, 0.03), (0, 0, 0))])])


class ToiletStallFactory:
    """A commercial WC cubicle (front +X = the door side): laminate side panels and a half-open door on legs, a white wall-hung
    toilet and cistern box inside, a paper holder (floor scenes: 'two toilets loose in an open room', 3 of 3 calls)."""
    def __init__(self, seed):
        r = random.Random(seed); self.c = tuple(STYLE.get("stall_rgb") or r.choice(((0.45, 0.52, 0.58), (0.55, 0.6, 0.6), (0.6, 0.53, 0.46))))     # kit stall_rgb: the reference's partition colour (B r22: grey, not pale wood)   # mid laminates: navy read black (floor H r4), white
        # stalls vanished against white walls (floor J r5, 3 of 3)

    def spawn_asset(self, i):
        D, W, H = 1.5, 0.95, 1.95
        panel = _flat(f"ir_stall_{int(self.c[2] * 100)}", self.c, 0.4); ceramic = _flat("ir_ceramic_white", (0.92, 0.92, 0.9), 0.08)
        chrome = _flat("ir_chrome", (0.8, 0.8, 0.82), 0.15, 1.0)
        sides = [("box", (0, sy * W / 2, H / 2 + 0.12), (D, 0.025, H - 0.24), (0, 0, 0)) for sy in (1, -1)]
        # a cubicle front: a fixed pilaster, a door hinged to it and opened ~35 deg, a chrome headrail over front and sides -- two side
        # panels and a loose door read as 'free-standing screens, no door, no headrail' (floor J r24, 3 of 3)
        pw, dw, a_ = 0.25, W - 0.25 - 0.02, -1.5   # swung INSIDE the cubicle against its side panel: a 0.7 m clear opening (user 10-18: stall doors must be open to pass; ajar 0.22 rad was a closed door, outward 0.6 'swung into the only aisle', floor H r43)
        pil = [("box", (D / 2, W / 2 - pw / 2, H / 2 + 0.06), (0.03, pw, H - 0.12), (0, 0, 0))]
        hx, hy = D / 2, W / 2 - pw
        door = [("box", (hx + math.sin(a_) * dw / 2, hy - math.cos(a_) * dw / 2, H / 2 + 0.12), (0.025, dw, H - 0.24), (0, 0, a_))]
        rail = [("box", (D / 2, 0, H + 0.02), (0.04, W + 0.04, 0.04), (0, 0, 0))] + \
               [("box", (0, sy * W / 2, H + 0.02), (D, 0.04, 0.04), (0, 0, 0)) for sy in (1, -1)]
        lock = [("box", (D / 2 + 0.02, W / 2 - pw + 0.04, 1.05), (0.02, 0.05, 0.05), (0, 0, 0))]
        legs = [("cyl", (x, sy * W / 2, 0.06), (0.015, 0.015, 0.12), (0, 0, 0)) for x in (-D / 2 + 0.05, D / 2 - 0.05) for sy in (1, -1)]
        bowl = [("rbox", (-D / 2 + 0.3, 0, 0.4), (0.5, 0.38, 0.32), (0, 0, 0)), ("box", (-D / 2 + 0.07, 0, 0.75), (0.12, 0.4, 0.4), (0, 0, 0)),
                ("box", (-D / 2 + 0.06, 0, 0.12), (0.1, 0.2, 0.24), (0, 0, 0))]   # bowl, cistern, wall bracket
        return _prims(f"ToiletStallFactory({i}).spawn_asset({i})", [(panel, sides + door + pil), (chrome, legs + rail + lock + [("cyl", (-D / 2 + 0.6, W / 2 - 0.04, 0.7),
                                                                    (0.06, 0.06, 0.1), (math.pi / 2, 0, 0))]), (ceramic, bowl)])


class WashBasinFactory:
    """Commercial wall-hung washbasin (front +X): white ceramic bowl on the wall, chrome tap, mirror above, soap and paper-towel
    dispensers beside (floor scenes 2026-10-16: Infinigen's pedestal sinks drew pink/green residential basins, 3 of 3 calls)."""
    def __init__(self, seed):
        self.seed = seed

    def spawn_asset(self, i):
        white = _flat("ir_ac_white", (0.86, 0.86, 0.85), 0.4); ceramic = _flat("ir_ceramic_white", (0.92, 0.92, 0.9), 0.08)
        chrome = _flat("ir_chrome", (0.8, 0.8, 0.82), 0.15, 1.0); mirror = _flat("ir_mirror", (0.9, 0.92, 0.93), 0.02, 1.0)
        return _prims(f"WashBasinFactory({i}).spawn_asset({i})",
                      [(ceramic, [("rbox", (0.22 + sx * 0.1925, 0, 0.8), (0.035, 0.55, 0.16), (0, 0, 0)) for sx in (1, -1)] +        # E3 r28 GEO-01 'a rounded flat-top solid, no bowl or drain': a hollow bowl, four rim walls round a floor 8 cm down
                                  [("rbox", (0.22, sy * 0.2575, 0.8), (0.42, 0.035, 0.16), (0, 0, 0)) for sy in (1, -1)] +
                                  [("box", (0.22, 0, 0.785), (0.40, 0.53, 0.03), (0, 0, 0))]),
                       (chrome, [("cyl", (0.06, 0, 0.93), (0.015, 0.015, 0.12), (0, 0, 0)), ("box", (0.11, 0, 0.98), (0.1, 0.02, 0.02), (0, 0, 0)),
                                 ("cyl", (0.12, 0, 0.375), (0.025, 0.025, 0.75), (0, 0, 0)), ("cyl", (0.22, 0, 0.8015), (0.022, 0.022, 0.004), (0, 0, 0))] +        # waste pipe to the floor: _place (+ the drain disc in the bowl)
                                [("box", (0.014, 0, 1.45 + sz * 0.41), (0.025, 0.64, 0.02), (0, 0, 0)) for sz in (1, -1)] +   # a chrome
                                [("box", (0.014, sy * 0.31, 1.45), (0.025, 0.02, 0.84), (0, 0, 0)) for sy in (1, -1)]),       # frame: the bare
                       # reflection of the tiles read as 'a tiled panel tilted off the wall' (floors A2 r6 / F3 r7, 4 calls)
                                                                                                       # stands an asset on its lowest point
                       (mirror, [("box", (0.01, 0, 1.45), (0.01, 0.6, 0.8), (0, 0, 0))]),
                       (white, [("box", (0.05, 0.45, 1.15), (0.1, 0.12, 0.22), (0, 0, 0)),              # soap
                                ("box", (0.06, -0.55, 1.3), (0.12, 0.3, 0.38), (0, 0, 0))])])         # paper towels


class LockerFactory:
    """A bank of 3-4 grey steel staff/patient lockers with vents and handles (front +X): a changing room's defining piece."""
    def __init__(self, seed):
        r = random.Random(seed); self.n = r.choice((3, 4)); self.c = tuple(STYLE["locker_rgb"]) if STYLE.get("locker_rgb") else r.choice(((0.55, 0.57, 0.6), (0.2, 0.35, 0.55), (0.75, 0.76, 0.76)))      # kit locker_rgb: I r35 'grey lockers, not blue'

    def spawn_asset(self, i):
        n, w, d, h = self.n, 0.4, 0.5, 1.8
        steel = _flat(f"ir_locker_{int(self.c[2] * 100)}", self.c, 0.4, 0.6); dark = _flat("ir_black_metal", (0.03, 0.03, 0.03), 0.4, 1.0)
        L = n * w
        doors = [("box", (d / 2, -L / 2 + (k + 0.5) * w, h / 2 + 0.05), (0.01, w - 0.02, h - 0.12), (0, 0, 0)) for k in range(n)]
        vents = [("box", (d / 2 + 0.006, -L / 2 + (k + 0.5) * w, h - 0.25 - j * 0.04), (0.004, w * 0.5, 0.012), (0, 0, 0))
                 for k in range(n) for j in range(4)]
        handles = [("box", (d / 2 + 0.015, -L / 2 + (k + 0.5) * w + w * 0.35, h / 2), (0.02, 0.02, 0.1), (0, 0, 0)) for k in range(n)]
        return _prims(f"LockerFactory({i}).spawn_asset({i})", [(steel, [("box", (0, 0, h / 2 + 0.05), (d, L, h - 0.1), (0, 0, 0))] + doors),
                                                                (dark, vents + handles + [("box", (0, 0, 0.025), (d - 0.04, L, 0.05), (0, 0, 0))])])


class ChangingBenchFactory:
    """A plain backless changing-room bench: slatted wood top on two steel legs (front +X)."""
    def __init__(self, seed):
        self.L = random.Random(seed).choice((1.2, 1.5))

    def spawn_asset(self, i):
        L = self.L
        wood = _flat("ir_bench_slat", (0.55, 0.4, 0.26), 0.5, wood=True); steel = _flat("ir_desk_frame", (0.75, 0.75, 0.76), 0.35, 0.8)
        slats = [("box", (-0.13 + k * 0.09, 0, 0.45), (0.07, L, 0.03), (0, 0, 0)) for k in range(4)]
        legs = [("box", (0, sy * (L / 2 - 0.12), 0.22), (0.3, 0.04, 0.44), (0, 0, 0)) for sy in (1, -1)]
        return _prims(f"ChangingBenchFactory({i}).spawn_asset({i})", [(wood, slats), (steel, legs)])


class TowelStackFactory:
    """Two to four folded towels in a stack (physio beds; clinic r18: 'no towels -- a showroom')."""
    def __init__(self, seed):
        r = random.Random(seed); self.n = r.randint(2, 4); self.c = r.choice(((0.92, 0.92, 0.9), (0.6, 0.75, 0.85), (0.75, 0.82, 0.78)))

    def spawn_asset(self, i):
        m = _flat(f"ir_towel_{int(self.c[0] * 100)}", self.c, 0.95)
        return _prims(f"TowelStackFactory({i}).spawn_asset({i})",
                      [(m, [("box", (0.005 * (k % 2), 0, 0.02 + k * 0.04), (0.3, 0.42, 0.04), (0, 0, 0.05 * (k % 2))) for k in range(self.n)])])


class PhysioKitFactory:
    """Therapy supplies against a wall (front +X): an open steel shelf with rolled towels, foam rollers and coiled bands, and two gym
    balls on the floor beside it (clinic r21: physio signs of use 3-4 -- 'bare mats, no balls, bands or towels')."""
    def __init__(self, seed):
        r = random.Random(seed); self.side = r.choice((1, -1))
        self.ball = r.choice(((0.1, 0.25, 0.5), (0.45, 0.3, 0.05), (0.12, 0.35, 0.2), (0.4, 0.4, 0.42)))

    def spawn_asset(self, i):
        sd = self.side
        steel = _flat("ir_desk_frame", (0.75, 0.75, 0.76), 0.35, 0.8); towel = _flat("ir_towel_92", (0.92, 0.92, 0.9), 0.95)
        foam = _flat("ir_foam_roller", (0.05, 0.25, 0.55), 0.8); band = [_flat(f"ir_band_{k}", c, 0.5) for k, c in
                                                                         enumerate(((0.6, 0.08, 0.06), (0.1, 0.3, 0.6), (0.5, 0.5, 0.05)))]
        ball = _flat(f"ir_gymball_{int(self.ball[2] * 100)}", self.ball, 0.3)
        W, D = 1.0, 0.4
        frame = [("box", (0, sy * (W / 2 - 0.015), 0.45), (D, 0.03, 0.9), (0, 0, 0)) for sy in (1, -1)] + \
                [("box", (0, 0, z), (D, W, 0.02), (0, 0, 0)) for z in (0.05, 0.45, 0.88)]
        towels = [("box", (0.02, -0.3 + k * 0.2, 0.89 + 0.05), (0.3, 0.16, 0.08), (0, 0, 0)) for k in range(4)]
        # standing upright on the middle shelf: lying flat and dark they read as 'slippers on a shoe rack' (physio r32)
        rollers = [("cyl", (0.0, -0.3 + k * 0.2, 0.46 + 0.19), (0.07, 0.07, 0.38), (0, 0, 0)) for k in range(4)]
        bands = [(band[k], [("cyl", (0.02, -0.3 + k * 0.3, 0.1), (0.1, 0.1, 0.06), (0, 0, 0))]) for k in range(3)]
        balls = [("sph", (D / 2 + 0.33, sd * 0.28, 0.33), (0.33, 0.33, 0.33), (0, 0, 0)),     # both in front, within the shelf's 1 m:
                 ("sph", (D / 2 + 0.27, -sd * 0.33, 0.27), (0.27, 0.27, 0.27), (0, 0, 0))]   # 2.2 / 1.6 m wide found no wall (r22, r24)
        return _prims(f"PhysioKitFactory({i}).spawn_asset({i})", [(steel, frame), (towel, towels), (foam, rollers), (ball, balls)] + bands)


class DumbbellRackFactory:
    """A two-tier dumbbell rack (front +X) with pairs of hex dumbbells, light to heavy (physio; clinic r18: 'no weights')."""
    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        frame = _flat("ir_black_metal", (0.03, 0.03, 0.03), 0.4, 1.0); bell = _flat("ir_dumbbell", (0.12, 0.12, 0.13), 0.5, 0.3)
        grip = _flat("ir_chrome", (0.8, 0.8, 0.82), 0.15, 1.0)
        legs = [("box", (sx * 0.15, sy * 0.48, 0.35), (0.04, 0.04, 0.7), (0, 0, 0)) for sx in (1, -1) for sy in (1, -1)]
        tiers = [("box", (0.05, 0, 0.35), (0.25, 1.0, 0.02), (0, 0, 0)), ("box", (0.0, 0, 0.65), (0.25, 1.0, 0.02), (0, 0, 0))]
        bells, grips = [], []
        for t, z in enumerate((0.36, 0.66)):
            for k in range(4):
                y = -0.36 + k * 0.24; s_ = 0.035 + 0.008 * (k + 4 * t)
                for dx in (-0.08, 0.08):
                    bells.append(("cyl", (0.05 + dx, y, z + s_), (s_, s_, 0.05), (0, math.pi / 2, 0)))
                grips.append(("cyl", (0.05, y, z + s_), (0.014, 0.014, 0.12), (0, math.pi / 2, 0)))
        return _prims(f"DumbbellRackFactory({i}).spawn_asset({i})", [(frame, legs + tiers), (bell, bells), (grip, grips)])


def _zinc(k):
    """ROOM_RACK_BARE_METAL=1: unpainted zinc-plated / galvanized steel (metallic exactly 1, rough 0.30-0.40, a slightly different tone per variant k)."""
    k = k % 4
    rgb = ((0.66, 0.68, 0.70), (0.60, 0.62, 0.64), (0.70, 0.71, 0.72), (0.63, 0.65, 0.66))[k]
    return _flat(f"ir_zinc_{k}", rgb, (0.30, 0.34, 0.37, 0.40)[k], 1.0)


class StorageRackFactory:
    """Steel warehouse rack (front +X): two upright frames per bay, orange step beams and solid decks on 4-5 levels, so the shelf
    filler finds every level (ABO wire racks: 0 items stocked on 9 racks, warehouse r1 2026-10-16: 'every rack is bare')."""
    def __init__(self, seed):
        r = random.Random(seed)
        self.L = r.choice((1.8, 2.4)); self.D = r.choice((0.8, 1.0)); self.H = r.choice((3.0, 3.6))   # pallet-rack height under a 5 m roof
                                                                                                # (warehouse r10: 'short shelving -- a stockroom')
        self.up = _ROOM_PICK.setdefault("rack_up", r.choice(((0.1, 0.22, 0.5), (0.35, 0.37, 0.4), (0.82, 0.82, 0.8))))   # one rack family
        if STYLE.get("rack_up_rgb"):
            self.up = tuple(STYLE["rack_up_rgb"])                  # kit rack_up_rgb: dark steel uprights (J ref: dark racks, yellow guards)
        self.deck = _ROOM_PICK.setdefault("rack_deck", tuple(STYLE["rack_deck_rgb"]) if STYLE.get("rack_deck_rgb") else r.choice(((0.62, 0.5, 0.36), (0.6, 0.62, 0.64))))      # kit rack_deck_rgb: one deck colour (M refs: uniform dark steel shelving)
        #   # per room (floor J r11: 'two
        # rack styles mixed', chipboard or galvanised)

    def spawn_asset(self, i):
        L, D, H = self.L, self.D, self.H
        if STYLE.get("rack_style") == "wire":                    # kit: chrome wire shelving (floors G / H utility refs: 'stainless wire racks'): round posts, thin chrome decks with cross wires, no beams
            ch = _flat("ir_wire_chrome", (0.8, 0.81, 0.83), 0.2, 1.0)
            zs = [0.15] + [0.15 + k * (H - 0.2) / 4.0 for k in range(1, 5)]
            posts = [("cyl", (sx * (D / 2 - 0.02), sy * (L / 2 - 0.02), H / 2), (0.016, 0.016, H), (0, 0, 0)) for sx in (1, -1) for sy in (1, -1)]
            decks = [("box", (0, 0, z), (D - 0.02, L - 0.02, 0.012), (0, 0, 0)) for z in zs]
            wires = [("box", (0, -L / 2 + 0.05 + k * (L - 0.1) / 9, z + 0.012), (D - 0.04, 0.006, 0.006), (0, 0, 0)) for z in zs for k in range(10)]
            return _prims(f"StorageRackFactory({i}).spawn_asset({i})", [(ch, posts + decks + wires)])
        beam_rgb = getattr(self, "beam_rgb", tuple(STYLE.get("rack_beam_rgb") or (0.85, 0.32, 0.05)))      # kit rack_beam_rgb: dark / yellow beams instead of orange (J ref)
        up = _flat(f"ir_rack_up_{int(self.up[2] * 100)}", self.up, 0.45, 0.6); beam = _flat(f"ir_rack_beam_{int(beam_rgb[1] * 100)}", beam_rgb, 0.4, 0.5)
        if os.environ.get("ROOM_RACK_BARE_METAL") == "1":
            up, beam = _zinc(i), _zinc(i + 1)                       # unpainted uprights and beams, tone varies per rack
        deck = _flat(f"ir_rack_deck_{int(self.deck[0] * 100)}", self.deck, 0.6, 0.0 if self.deck[0] > self.deck[2] + 0.1 else 0.7)
        posts = [(sx * (D / 2 - 0.04), sy * (L / 2 - 0.04), H / 2, 0.07, 0.07, H) for sx in (1, -1) for sy in (1, -1)]
        braces = [(0, sy * (L / 2 - 0.04), z, D - 0.08, 0.03, 0.03) for sy in (1, -1) for z in (0.3, H / 2, H - 0.3)]
        zs = [0.12] + [0.12 + k * (H - 0.25) / 4.6 for k in range(1, 5)] + [H - 0.04]
        beams = [(sx * (D / 2 - 0.04), 0, z - 0.06, 0.05, L - 0.08, 0.1) for sx in (1, -1) for z in zs]
        decks = [(0, 0, z + 0.005, D - 0.06, L - 0.1, 0.02) for z in zs]
        groups = [(up, posts + braces), (beam, beams), (deck, decks)]
        if STYLE.get("rack_guards") == "yellow":                  # kit rack_guards=yellow: safety-yellow base guards on every upright + a yellow end bumper rail (J ref: 'dark steel racks with yellow guards and bollards')
            yel = _flat("ir_rack_guard_yellow", (0.95, 0.75, 0.05), 0.5)
            guards = [(sx * (D / 2 - 0.04), sy * (L / 2 - 0.04), 0.25, 0.14, 0.14, 0.5) for sx in (1, -1) for sy in (1, -1)] + [(sx * (D / 2 - 0.04), 0.0, 0.5, 0.05, L - 0.1, 0.06) for sx in (1, -1)]
            groups.append((yel, guards))
        return _parts_object(f"StorageRackFactory({i}).spawn_asset({i})", groups)


class SupplyShelfFactory(StorageRackFactory):
    """Clinic supply shelving: the same rack (its name stays StorageRackFactory for the shelf filler) in white, 2 m tall -- orange
    pallet racking read as 'a shop back room, not sterilisation' (floor E3 r6, 3 of 3)."""
    def __init__(self, seed):
        super().__init__(seed)
        r = random.Random(seed + 1)
        self.L = r.choice((0.9, 1.2)); self.D = 0.45; self.H = 2.0
        self.up = (0.9, 0.9, 0.9); self.deck = (0.86, 0.87, 0.88); self.beam_rgb = (0.88, 0.88, 0.88)


class StockShelfFactory(SupplyShelfFactory):
    """Back-stockroom shelving (name stays StorageRackFactory for the filler): galvanised, 1.5-1.8 m runs, 2.1 m tall -- the 0.9-1.2 m
    clinic unit read as 'one small shelf in an empty room' in café/shop stockrooms (floors G r13, H r14, 3 of 3 each)."""
    def __init__(self, seed):
        super().__init__(seed)
        r = random.Random(seed + 3)
        self.L = r.choice((1.5, 1.8)); self.D = 0.55; self.H = 2.1
        self.up = (0.62, 0.63, 0.65); self.deck = (0.6, 0.62, 0.64); self.beam_rgb = (0.62, 0.63, 0.65)


class OfficeShelfFactory(SupplyShelfFactory):
    """A plain office bookcase / binder shelf (name stays StorageRackFactory for the filler): the Infinigen bookcase came out as a
    purple kids' cube shelf (floor A2 r5, 3 of 3)."""
    def __init__(self, seed):
        super().__init__(seed)
        r = random.Random(seed + 2)
        self.L = r.choice((0.8, 1.0)); self.D = 0.35; self.H = 1.8
        c = r.choice(((0.86, 0.86, 0.85), (0.32, 0.33, 0.35)))   # no pine: 'a raw pine rack of books -- a home study' (floor F3 r7, 3/3)
        self.up = c; self.deck = c; self.beam_rgb = c

    def spawn_asset(self, i):
        # a closed carcass -- side panels, back, top, plinth -- not posts and beams: 'a white ladder utility rack' (floor A2 r6, 3 of 3)
        L, D, H, t = self.L, self.D, self.H, 0.02
        m = _flat(f"ir_office_shelf_{int(self.up[0] * 100)}", self.up, 0.45)
        zs = [0.08] + [0.08 + k * (H - 0.12) / 4 for k in range(1, 4)]
        parts = [(0, sy * (L / 2 - t / 2), H / 2, D, t, H) for sy in (1, -1)] + [(-D / 2 + t / 2, 0, H / 2, t, L, H), (0, 0, H - t / 2, D, L, t),
                 (D / 2 - 0.02, 0, 0.04, 0.02, L - 2 * t, 0.08)] + [(0, 0, z, D - t, L - 2 * t, t) for z in zs]
        try:                                                     # books and binders on every shelf (floor C r19: 'the bookcases look empty')
            import bmesh
            from room_planner import proc_bookstore as pb
            r = random.Random(i * 7 + int(L * 100)); bm = bmesh.new(); bm.loops.layers.uv.verify(); uvl = bm.loops.layers.uv.active; n = 0
            for z in zs:
                if r.random() < 0.85:
                    a0 = r.uniform(0.0, 0.15) * L
                    n += pb._row(bm, uvl, r, D / 2 - 0.04, -L / 2 + t + 0.02 + a0, L / 2 - t - 0.02, z + t / 2, 1, height=(0.2, 0.34), depth=(0.15, 0.27), thick=(0.02, 0.06))
            if n:
                return pb._object(f"StorageRackFactory({i}).spawn_asset({i})", [(m, parts)], bm, pb.atlas_material(r.randrange(pb.meta()["n_atlases"])))
            bm.free()
        except Exception:                                        # noqa: BLE001 -- books are an extra; the plain case stays
            pass
        return _parts_object(f"StorageRackFactory({i}).spawn_asset({i})", [(m, parts)])


class AutoclaveFactory:
    """Benchtop steam autoclave (front +X): a steel body with a round dark chamber door and a small display -- the piece that makes a
    sterilisation room read as one (floor E3 r6: 'no autoclave, a stockroom with a kitchenette', 3 of 3)."""
    def __init__(self, seed):
        # under the 1.45 m upper cabinets of a 0.94 m worktop (floor E3 r7: 0.45 m tall / 0.5 m deep found 'no fit', 3 of 3 saw none)
        r = random.Random(seed); self.W = r.choice((0.42, 0.5)); self.H = r.choice((0.34, 0.38))

    def spawn_asset(self, i):
        W, H, D = self.W, self.H, 0.42
        steel = _flat("ir_autoclave_body", (0.78, 0.79, 0.8), 0.3, 0.7); door = _flat("ir_autoclave_door", (0.12, 0.13, 0.14), 0.35, 0.8)
        disp = _flat("ir_autoclave_display", (0.15, 0.45, 0.65), 0.2)
        return _prims(f"AutoclaveFactory({i}).spawn_asset({i})", [
            (steel, [("box", (0, 0, H / 2), (D, W, H), (0, 0, 0)),          # a box, not a rounded blob ('a chrome
                      ("box", (0.02, W / 2 + 0.2, 0.08), (0.3, 0.26, 0.16), (0, 0, 0))]),   # sphere like a speaker', E3 r10) + an ultrasonic bath
            # a square chamber door with a lever, not a round porthole: two round-door boxes read as 'a washer and dryer' (floor E3 r15, 3/3)
            (door, [("box", (D / 2 + 0.008, -W * 0.08, H * 0.48), (0.016, W * 0.62, H * 0.62), (0, 0, 0)),
                    ("box", (D / 2 + 0.03, -W * 0.08 + W * 0.26, H * 0.48), (0.03, 0.02, H * 0.3), (0, 0, 0))]),
            (disp, [("box", (D / 2 + 0.005, W * 0.33, H * 0.62), (0.01, W * 0.18, H * 0.16), (0, 0, 0))])])


class DisplayCoolerFactory:
    """Upright glass-door drinks cooler (front +X), 0.75 x 0.7 x 2.0 m: a dark cabinet, a lit header, an aluminium-framed glass
    door, a white-lit interior and 5 shelves of bottles and cans in rows. Infinigen's BeverageFridge is an under-counter unit and
    rendered as 'knee-high black boxes' (shop r2 critic)."""
    PACK = ((0.75, 0.1, 0.08), (0.1, 0.35, 0.7), (0.95, 0.6, 0.1), (0.2, 0.55, 0.2), (0.85, 0.85, 0.8), (0.1, 0.1, 0.1))

    def __init__(self, seed):
        r = random.Random(seed)
        self.r = r; self.body = r.choice(((0.85, 0.85, 0.84), (0.6, 0.6, 0.62)))   # no black: a black side edge-on read as a slab (floor I r2-r4, 3/3)   # style eval G: a coral cooler broke two cafes

    def spawn_asset(self, i):
        r, W, D, H = self.r, 0.75, 0.7, 2.0
        body = _flat(f"ir_cooler_{int(self.body[0] * 100)}", self.body, 0.4, 0.3); alu = _flat("ir_wh_alu", (0.8, 0.8, 0.82), 0.3, 1.0)
        glass = _flat("ir_cooler_glass", (0.9, 0.95, 0.97), 0.03, transmission=0.95)
        lit = _flat("ir_cooler_lit", (1.0, 1.0, 1.0), 0.4)
        lit.node_tree.nodes["Principled BSDF"].inputs["Emission Color"].default_value = ((0.4, 0.65, 1.0, 1) if os.environ.get("ROOM_COOLER_BLUE") == "1" else (0.92, 0.97, 1.0, 1))
        lit.node_tree.nodes["Principled BSDF"].inputs["Emission Strength"].default_value = 2.5
        shell = [("box", (-D / 2 + 0.02, 0, H / 2), (0.04, W, H), (0, 0, 0)), ("box", (0, W / 2 - 0.02, H / 2), (D, 0.04, H), (0, 0, 0)),
                 ("box", (0, -W / 2 + 0.02, H / 2), (D, 0.04, H), (0, 0, 0)), ("box", (0, 0, 0.06), (D, W, 0.12), (0, 0, 0)),
                 ("box", (0, 0, H - 0.1), (D, W, 0.2), (0, 0, 0))]
        frame = [("box", (D / 2 - 0.01, 0, 0.14), (0.03, W, 0.04), (0, 0, 0)), ("box", (D / 2 - 0.01, 0, H - 0.22), (0.03, W, 0.04), (0, 0, 0)),
                 ("box", (D / 2 - 0.01, W / 2 - 0.03, H / 2), (0.03, 0.04, H - 0.32), (0, 0, 0)),
                 ("box", (D / 2 - 0.01, -W / 2 + 0.03, H / 2), (0.03, 0.04, H - 0.32), (0, 0, 0)),
                 ("box", (D / 2 + 0.02, -W / 2 + 0.08, H / 2), (0.03, 0.025, 0.7), (0, 0, 0))]        # handle
        shelves = [("box", (0.0, 0, z), (D - 0.12, W - 0.08, 0.012), (0, 0, 0)) for z in (0.16, 0.5, 0.84, 1.18, 1.52)]
        stock = {}
        for z in (0.16, 0.5, 0.84, 1.18, 1.52):
            c = r.choice(self.PACK); can = r.random() < 0.4
            h, rad = (0.12, 0.033) if can else (0.24, 0.035)
            for row in range(3):
                for k in range(int((W - 0.12) / (2 * rad + 0.008))):
                    if r.random() < 0.1:                         # a few sold
                        continue
                    y = -W / 2 + 0.07 + rad + k * (2 * rad + 0.008)
                    stock.setdefault(c, []).append(("cyl", (D / 2 - 0.1 - row * 0.12, y, z + 0.006 + h / 2), (rad, rad * (1 if can else 0.6), h), (0, 0, 0)))
        groups = [(body, shell), (alu, frame + shelves), (lit, [("box", (-D / 2 + 0.045, 0, H / 2), (0.005, W - 0.1, H - 0.4), (0, 0, 0)),
                                                                ("box", (D / 2 - 0.005, 0, H - 0.1), (0.01, W - 0.1, 0.14), (0, 0, 0))]),
                  (glass, [("box", (D / 2 - 0.01, 0, H / 2 - 0.04), (0.008, W - 0.06, H - 0.36), (0, 0, 0))])]
        groups += [(_flat(f"ir_pack_{int(c[0] * 100)}_{int(c[1] * 100)}_{int(c[2] * 100)}", c, 0.3, 0.5), parts) for c, parts in stock.items()]
        o = _prims(f"DisplayCoolerFactory({i}).spawn_asset({i})", groups)
        ld = bpy.data.lights.new(f"ir_cooler_{i}", "AREA"); ld.shape = "RECTANGLE"; ld.size, ld.size_y = 0.6, 1.6; ld.energy = 25.0
        lo = bpy.data.objects.new(f"PointLampFactory(cooler).spawn_asset({i})", ld)
        bpy.context.scene.collection.objects.link(lo); lo.parent = o; lo.location = (D / 2 - 0.15, 0, H / 2); lo.rotation_euler = (0, math.pi / 2, 0)
        return o


_HDR_CYCLE = [0]                                         # next aisle-board print for header_cycle (per Blender process = per activity pass)


class GondolaFactory:
    """Supermarket gondola (front +X): a base deck and 4 shelves per side, a price strip on every shelf edge, a coloured header on
    one end. Double-sided (0.9 m deep, free-standing aisles) or single-sided (0.45 m, against a wall). 1.2-2.4 m long, 1.45-1.6 m."""
    double = True

    def __init__(self, seed):
        r = random.Random(seed)
        self.L = float(STYLE["gondola_L"]) if STYLE.get("gondola_L") else r.choice((1.25, 1.875, 2.5)); self.H = r.uniform(*(STYLE.get("gondola_h") or (1.45, 1.6))); self.header = tuple(STYLE["accent_rgb"]) if STYLE.get("accent_rgb") else r.choice(HEADER_COLOURS)   # kit accent_rgb: the pharmacy's green

    def spawn_asset(self, i):
        L, H = self.L, self.H
        D = 0.9 if self.double else 0.45
        gb_ = STYLE.get("gondola_body_rgb")                                                 # kit gondola_body_rgb: a light grey metal body instead of white laminate (I r35: 'plain white slab shelving')
        body = _flat("ir_gondola_white", (0.86, 0.86, 0.85), 0.35, 0.3) if not gb_ else _flat(f"ir_gondola_body_{int(gb_[0] * 100)}", tuple(gb_), 0.4, 0.3)
        sp_ = STYLE.get("price_strip_rgb"); strip = _flat("ir_price_strip", (0.92, 0.9, 0.55), 0.4) if not sp_ else _flat(f"ir_price_strip_{int(sp_[2] * 100)}", tuple(sp_), 0.4)      # kit price_strip_rgb: blue shelf-edge strips (I r34 refs)
        head = _flat(f"ir_header_{HEADER_COLOURS.index(self.header) if self.header in HEADER_COLOURS else int(self.header[1] * 100)}", self.header, 0.5)
        sides = (1, -1) if self.double else (1,)
        parts, strips, shade, bands = [], [], [], []
        back_x = 0.0 if self.double else -D / 2 + 0.02
        parts.append((back_x, 0, H / 2, 0.04, L, H))                                    # back panel / spine
        parts += [(sx * (D / 2 - 0.02), sy * (L / 2 - 0.02), H / 2, 0.04, 0.04, H) for sx in (1, -1) for sy in (1, -1)]   # corner posts, not
        # solid end panels: 'tall blank white end panels like cubicle partitions' (floor I r12-r13, 3 of 3 each)
        for sx in sides:
            x_mid = sx * D / 4 if self.double else 0.0
            depth = D / 2 - 0.03 if self.double else D - 0.05
            (bands if (VENUE == "pharmacy" and STYLE.get("band_rgb")) else parts).append((x_mid, 0, 0.06, depth, L - 0.04, 0.12))                       # base deck (a green band in the pharmacy ref)
            for k in range(1, 5):
                z = 0.12 + k * (H - 0.2) / 4.6
                parts.append((x_mid, 0, z, depth, L - 0.04, 0.02))
                strips.append((x_mid + sx * depth / 2, 0, z - 0.01, 0.01, L - 0.06, 0.035))
                if os.environ.get("ROOM_SHELF_UNDERSHADE") == "1":                      # contact shadow (S13 review): a 6 mm dark face under each board + a dark band on the back panel below it
                    shade.append((x_mid, 0, z - 0.013, depth - 0.01, L - 0.05, 0.006))
                    shade.append((back_x + (sx * 0.03 if self.double else 0.03), 0, z - 0.06, 0.004, L - 0.06, 0.1))
        # the header carries an aisle word in white block letters on both faces (floor I r9: 'large blank coloured boards on the shelf
        # tops read as cubicle partitions', 3 of 3)
        _hw = tuple(STYLE.get("header_words") or HEADER_WORDS); word = _hw[(i * 7 + int(L * 10)) % len(_hw)]; n = len(word); lw = D * 0.55 / max(n, 4)   # spread over the
        # list, not random: 'DELI five times, COLD four times' (floor I r28, 3 of 3)
        zh = H + (0.14 if STYLE.get("header_flat") else 0.55)                                            # hung above the gondola on two rods, smaller: at H + 0.14 the boards sat
        glyphs = []                                              # at eye level and 'filled the frame' (floor I r28, 3 of 3)                                              # real words in a stroke font: random strokes read as 'mirrored
        gw, gh, t_ = lw * 0.6, 0.12, 0.014                       # nonsense text' (floor I r27, 3 of 3); solid blocks as 'blank
        for k, ch in enumerate(word):                            # placeholder signs' (I r21-r26)
            xt = -lw * n / 2 + (k + 0.5) * lw
            for sy in (1, -1):                                   # each face reads left to right from its own side: x_world = -sy * x_text
                glyphs += [(-sy * (xt + ux * gw), L / 2 + 0.01 + sy * 0.012, zh + uz * gh * 0.8, max(t_, uw * gw), 0.004, max(t_, uh * gh * 0.8))
                           for ux, uz, uw, uh in _STROKES[ch]]
        ink = _flat("ir_header_ink", (0.95, 0.95, 0.93), 0.5) if not STYLE.get("header_flat") else _flat("ir_header_ink_dark", (0.04, 0.04, 0.045), 0.5)
        hk = {"pharmacy": "header_pharmacy", "boutique": "header_boutique"}.get(VENUE, "header_grocery")
        hp = _pick_print(hk, i * 7 + int(L * 10))                # a typeset aisle word on a coloured board; the stroke font read as 'odd lettering'
        if STYLE.get("header_cycle") and hk == "header_grocery":    # kit header_cycle: aisle boards take the prints in turn, so no word repeats until all 8 are used (I r36: 'identical FOOD boards across several aisles')
            _fs = sorted(PRINT_ROOT.glob("header_grocery_*.png"))
            if _fs:
                hp = _fs[_HDR_CYCLE[0] % len(_fs)]; _HDR_CYCLE[0] += 1
        if STYLE.get("header_flat"):                               # kit header_flat: uniform accent board, dark words (S37 r2: multicolour printed boards)
            hp = None
        if hp is not None:
            head, glyphs = _printed(hp, self.header, 0.5), []
        o = _parts_object(f"{type(self).__name__}({i}).spawn_asset({i})",
                          [(body, parts), (strip, strips), (head, [(0, L / 2 + 0.01, zh, D * 0.7, 0.02, 0.2)]), (ink, glyphs)] + ([(_flat("ir_shelf_shade", (0.04, 0.04, 0.045), 0.9), shade)] if shade else []) + ([(_flat("ir_gondola_band", tuple(STYLE["band_rgb"]), 0.45), bands)] if bands else []) + [
                           (body, [(sx * D * 0.25, L / 2 + 0.01, (H + zh - 0.1) / 2, 0.012, 0.012, zh - 0.1 - H) for sx in (1, -1)])])
        return o


class WallGondolaFactory(GondolaFactory):
    double = False


class ChestFreezerFactory:
    """Supermarket chest freezer (front +X): white body, dark inner tub under a glass lid, 1.2-2.0 m long, 0.85 m high."""
    def __init__(self, seed):
        self.L = random.Random(seed).uniform(1.2, 2.0)

    def spawn_asset(self, i):
        L = self.L
        white = _flat("ir_appliance_white", (0.88, 0.88, 0.87), 0.3); dark = _flat("ir_freezer_inner", (0.15, 0.2, 0.25), 0.5)
        glass = _flat("ir_dome_glass", (0.95, 0.95, 0.95), 0.02, transmission=1.0)
        fb_ = STYLE.get("freezer_body_rgb") or STYLE.get("gondola_body_rgb")        # kit freezer_body_rgb (else gondola_body_rgb): a dark open tub with frozen product visible under the lid (S37 r3)
        if fb_:
            body = _flat(f"ir_freezer_body_{int(fb_[0] * 100)}", tuple(fb_), 0.4, 0.3); r_ = random.Random(i * 31 + int(L * 10)); t = 0.05
            walls = [(0, 0, 0.04, 0.8, L, 0.08), (0.4 - t / 2, 0, 0.4, t, L, 0.8), (-0.4 + t / 2, 0, 0.4, t, L, 0.8), (0, L / 2 - t / 2, 0.4, 0.8, t, 0.8), (0, -L / 2 + t / 2, 0.4, 0.8, t, 0.8)]
            groups = [(body, walls), (dark, [(0, 0, 0.09, 0.7, L - 0.1, 0.02)]), (glass, [(0, 0, 0.84, 0.76, L - 0.06, 0.012)])]
            cols = {}
            for ix in range(int((L - 0.2) // 0.22)):
                for iy in range(3):
                    c = r_.choice(((0.9, 0.2, 0.2), (0.15, 0.4, 0.85), (0.95, 0.75, 0.15), (0.2, 0.65, 0.4), (0.9, 0.9, 0.9), (0.9, 0.4, 0.7)))
                    cols.setdefault(c, []).append((-0.22 + iy * 0.22, -L / 2 + 0.2 + ix * 0.22, 0.62 + r_.uniform(-0.05, 0.08), 0.19, 0.2, 0.2))
            groups += [(_flat(f"ir_freezer_pack_{int(c[0] * 100)}_{int(c[1] * 100)}_{int(c[2] * 100)}", c, 0.5), ps) for c, ps in cols.items()]
            return _parts_object(f"ChestFreezerFactory({i}).spawn_asset({i})", groups)
        return _parts_object(f"ChestFreezerFactory({i}).spawn_asset({i})",
                             [(white, [(0, 0, 0.4, 0.8, L, 0.8)]), (dark, [(0, 0, 0.79, 0.7, L - 0.1, 0.02)]),
                              (glass, [(0, 0, 0.84, 0.76, L - 0.06, 0.012)])])


class RegisterFactory:
    """Point-of-sale register (front +X): a till base, a card reader and a customer-facing screen on a stem."""
    def __init__(self, seed):
        self.seed = seed

    def spawn_asset(self, i):
        black = _flat("ir_black_metal", (0.03, 0.03, 0.03), 0.4, 1.0); screen = _screen(i, "register")
        return _parts_object(f"RegisterFactory({i}).spawn_asset({i})",
                             [(black, [(0, 0, 0.05, 0.36, 0.42, 0.1), (0.0, 0, 0.2, 0.04, 0.04, 0.2), (0.15, 0.25, 0.03, 0.08, 0.06, 0.06),
                                       (-0.02, 0, 0.36, 0.03, 0.36, 0.26)]),            # a black bezel: the print used to wrap the slab's edges
                              (screen, [(-0.02 + 0.0155, 0, 0.36, 0.002, 0.33, 0.22)])])   # (user mark S15 r15: 'the POS image wraps the whole box')


class GrinderFactory:
    """Coffee grinder (front +X): a body, a dark bean hopper on top, a spout."""
    def __init__(self, seed):
        self.c = (0.55, 0.56, 0.58) if STYLE.get("espresso_finish") == "steel" else random.Random(seed).choice(((0.03, 0.03, 0.03), (0.62, 0.62, 0.64), (0.85, 0.85, 0.83)))   # kit: stainless, like the machine

    def spawn_asset(self, i):
        body = _flat("ir_steel", (0.62, 0.62, 0.64), 0.2, 1.0); hop = _flat("ir_black_metal", (0.03, 0.03, 0.03), 0.4, 1.0)     # the espresso machine's own stainless and black (a scanned body on a 0.2 m box read as a stone block, S8/S10)
        return _prims(f"GrinderFactory({i}).spawn_asset({i})",
                      [(body, [("cyl", (0, 0, 0.03), (0.09, 0.09, 0.06), (0, 0, 0)), ("cyl", (0, 0, 0.18), (0.055, 0.055, 0.24), (0, 0, 0)), ("box", (0.1, 0, 0.12), (0.05, 0.05, 0.04), (0, 0, 0))]),
                       (hop, [("cyl", (0, 0, 0.36), (0.07, 0.07, 0.14), (0, 0, 0)), ("cyl", (0, 0, 0.44), (0.03, 0.03, 0.03), (0, 0, 0))])])


class CupStackFactory:
    """A stack of 4-8 white or kraft takeaway cups."""
    def __init__(self, seed):
        r = random.Random(seed); self.n = r.randint(4, 8); self.c = r.choice(((0.92, 0.92, 0.9), (0.62, 0.45, 0.3)))

    def spawn_asset(self, i):
        m = _flat(f"ir_cup_{int(self.c[0] * 100)}", self.c, 0.5); h = 0.1 + 0.02 * self.n          # nested cups: a tapered stack, not a 8 cm box tower
        return _prims(f"CupStackFactory({i}).spawn_asset({i})",
                      [(m, [("cyl", (0, 0, h / 2), (0.035, 0.035, h), (0, 0, 0)), ("cyl", (0, 0, h - 0.004), (0.043, 0.043, 0.008), (0, 0, 0))])])


class PastryCaseFactory:
    """A glass pastry case on the counter: a base, two shelves of pastries behind glass."""
    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        r = self.r
        base = _flat("ir_black_metal", (0.03, 0.03, 0.03), 0.4, 1.0); glass = _flat("ir_dome_glass", (0.95, 0.95, 0.95), 0.02, transmission=1.0)
        # variety (S10 r10 'all identical round beige buns'): croissant, eclair, fruit tart, cake slice, macaron, donut, muffin, each its own colours
        groups = {}

        def add(name, rgb, prim, rough=0.6):
            groups.setdefault((name, rgb, rough), []).append(prim)
        DOUGH, CHOC, CREAM = (0.78, 0.5, 0.2), (0.17, 0.09, 0.05), (0.95, 0.92, 0.82)
        FRUIT = ((0.75, 0.1, 0.15), (0.15, 0.15, 0.4), (0.9, 0.72, 0.15), (0.55, 0.12, 0.3)); PINK = ((0.92, 0.6, 0.66), (0.95, 0.95, 0.9), CHOC)
        PASTEL = ((0.92, 0.6, 0.7), (0.6, 0.82, 0.7), (0.95, 0.85, 0.5), (0.62, 0.56, 0.86), (0.95, 0.65, 0.4))
        items = None
        bk_ = STYLE.get("bread_display") == "bakery"            # S35 r17 CNT-04: a bakery's case is FULL: two rows of 8 per tier (16), staggered, a bake tone per item
        spots_ = ([(-0.09 + 0.18 * (j % 2) + r.uniform(-0.015, 0.015), -0.315 + (j // 2) * 0.09 + (0.04 if j % 2 else 0.0)) for j in range(16)] if bk_ else None)
        for z in (0.03, 0.22):
            for k in range(16 if bk_ else 6):
                x, y = (spots_[k] if bk_ else (r.uniform(-0.1, 0.1), -0.3 + k * 0.12))
                if bk_ and r.random() < 0.08:
                    continue                                          # one gap in a dozen
                DOUGH = r.choice(((0.78, 0.5, 0.2), (0.62, 0.36, 0.14), (0.86, 0.66, 0.38), (0.45, 0.24, 0.1))) if bk_ else (0.78, 0.5, 0.2)
                kind = r.choice(("croissant", "eclair", "tart", "slice", "macaron", "donut", "muffin") if not bk_ else ("croissant", "croissant", "bun", "bun", "muffin", "donut", "tart", "eclair"))
                if kind == "croissant":                                   # a crescent of three ellipsoids
                    yw = r.uniform(0, 3.14)
                    for dy, sc in ((-0.03, 0.7), (0.0, 1.0), (0.03, 0.7)):
                        add("croissant", DOUGH, ("sph", (x, y + dy * 0.9, z + 0.02 + 0.006 * sc), (0.03 * sc, 0.024 * sc, 0.02 * sc), (0, 0, yw + dy * 6)))
                elif kind == "bun":
                    add("bun", DOUGH, ("sph", (x, y, z + 0.024), (0.036 * r.uniform(0.85, 1.2), 0.036 * r.uniform(0.85, 1.2), 0.028), (0, 0, r.uniform(0, 3.14))))
                elif kind == "eclair":
                    add("eclair", DOUGH, ("sph", (x, y, z + 0.018), (0.06, 0.022, 0.018), (0, 0, 1.57)))
                    add("eclair_top", CHOC, ("sph", (x, y, z + 0.03), (0.058, 0.02, 0.008), (0, 0, 1.57)), 0.3)
                elif kind == "tart":
                    add("tart", (0.8, 0.6, 0.3), ("cyl", (x, y, z + 0.01), (0.04, 0.032, 0.02), (0, 0, 0)))
                    f = r.choice(FRUIT); add("tart_fruit", f, ("sph", (x, y, z + 0.026), (0.03, 0.03, 0.013), (0, 0, 0)), 0.3)
                elif kind == "slice":
                    c = r.choice(PINK)
                    add("slice", (0.9, 0.8, 0.55), ("box", (x, y, z + 0.022), (0.075, 0.05, 0.034), (0, 0, r.uniform(-0.4, 0.4))))
                    add("slice_top", c, ("box", (x, y, z + 0.042), (0.077, 0.052, 0.006), (0, 0, 0)), 0.4)
                elif kind == "macaron":
                    c = r.choice(PASTEL)
                    add("macaron", c, ("cyl", (x, y, z + 0.008), (0.026, 0.026, 0.012), (0, 0, 0))); add("macaron", c, ("cyl", (x, y, z + 0.03), (0.026, 0.026, 0.012), (0, 0, 0)))
                    add("macaron_fill", CREAM, ("cyl", (x, y, z + 0.019), (0.022, 0.022, 0.01), (0, 0, 0)))
                elif kind == "donut":
                    c = r.choice(PINK)
                    add("donut", DOUGH, ("cyl", (x, y, z + 0.014), (0.04, 0.04, 0.026), (0, 0, 0)))
                    add("donut_glaze", c, ("cyl", (x, y, z + 0.029), (0.038, 0.036, 0.006), (0, 0, 0)), 0.3)
                else:                                                      # muffin
                    add("muffin", (0.7, 0.45, 0.2), ("cyl", (x, y, z + 0.014), (0.028, 0.034, 0.028), (0, 0, 0)))
                    add("muffin_top", r.choice((CHOC, (0.62, 0.38, 0.16))), ("sph", (x, y, z + 0.034), (0.036, 0.036, 0.022), (0, 0, 0)))
        pastry_groups = [(_flat(f"ir_pastry_{n}_{int(c[0] * 100)}{int(c[1] * 100)}{int(c[2] * 100)}", c, rg), ps) for (n, c, rg), ps in groups.items()]
        glow = None
        if STYLE.get("mood") in ("dark_moody", "warm_evening"):        # warm interior light under the top and each shelf (S10: 'pastry-case warm highlights')
            glow = _flat("ir_case_glow", (1.0, 0.75, 0.42), 0.4)
            gb = glow.node_tree.nodes["Principled BSDF"]; gb.inputs["Emission Color"].default_value = (1.0, 0.72, 0.38, 1); gb.inputs["Emission Strength"].default_value = 6.0
        return _prims(f"PastryCaseFactory({i}).spawn_asset({i})",
                      [(base, [("box", (0, 0, 0.015), (0.42, 0.78, 0.03), (0, 0, 0)), ("box", (0, 0, 0.21), (0.4, 0.76, 0.01), (0, 0, 0))]),
                       ] + pastry_groups + ([(glow, [("box", (0, 0, 0.402), (0.36, 0.72, 0.008), (0, 0, 0)), ("box", (0, 0, 0.202), (0.36, 0.72, 0.008), (0, 0, 0))])] if glow is not None else []) + [
                       (glass, [("box", (0.2, 0, 0.21), (0.01, 0.78, 0.4), (0, 0, 0)), ("box", (-0.2, 0, 0.21), (0.01, 0.78, 0.4), (0, 0, 0)),
                                ("box", (0, 0.39, 0.21), (0.42, 0.01, 0.4), (0, 0, 0)), ("box", (0, -0.39, 0.21), (0.42, 0.01, 0.4), (0, 0, 0)),
                                ("box", (0, 0, 0.41), (0.42, 0.78, 0.01), (0, 0, 0))])])


class SyrupRackFactory:
    """A row of 4-6 syrup bottles with pumps on a small tray."""
    def __init__(self, seed):
        self.n = random.Random(seed).randint(4, 6)

    def spawn_asset(self, i):
        tray = _flat("ir_black_metal", (0.03, 0.03, 0.03), 0.4, 1.0)
        cols = [_flat(f"ir_syrup_{k}", c, 0.12) for k, c in enumerate(((0.4, 0.22, 0.07), (0.34, 0.06, 0.06), (0.12, 0.24, 0.1), (0.78, 0.73, 0.58)))]
        groups = [(tray, [("box", (0, 0, 0.01), (0.1, 0.09 * self.n, 0.02), (0, 0, 0))])]
        for k in range(self.n):                                  # bottles: body, shoulder, neck, pump (S10: 'coloured blocks')
            y = -0.045 * (self.n - 1) + k * 0.09
            groups.append((cols[k % 4], [("cyl", (0, y, 0.11), (0.032, 0.032, 0.18), (0, 0, 0)), ("cyl", (0, y, 0.215), (0.016, 0.016, 0.04), (0, 0, 0))]))
            groups.append((tray, [("cyl", (0, y, 0.27), (0.008, 0.008, 0.07), (0, 0, 0)), ("box", (0.012, y, 0.31), (0.03, 0.01, 0.012), (0, 0, 0))]))
        return _prims(f"SyrupRackFactory({i}).spawn_asset({i})", groups)


# ---- office -------------------------------------------------------------------------------------------------------------------------
DIVIDER = [(0.42, 0.45, 0.47), (0.28, 0.36, 0.3), (0.55, 0.52, 0.46), (0.2, 0.25, 0.32)]


class WorkstationPodFactory:
    """Bench workstation (front +X = the +x row): 2x2 or 2x3 desks back to back, a fabric divider screen down the spine, a pedestal
    and a monitor (stand + screen) on every desk. obj['seats'] lists (x, y, yaw) seat spots in local frame for the chairs."""
    def __init__(self, seed, n=None):
        r = random.Random(seed)
        self.n = n or r.choice((2, 3, 3, 4)); self.w = r.uniform(1.2, 1.4); self.d = 0.7; self.div = r.choice(DIVIDER)   # 4/6/6/8 desks
        self.dual = r.random() < 0.4
        self.top = r.choice(((0.88, 0.87, 0.84), (0.55, 0.42, 0.3), (0.3, 0.3, 0.3)))

    def spawn_asset(self, i):
        n, w, d = self.n, self.w, self.d
        top = _flat(f"ir_desk_top_{int(self.top[0] * 100)}", self.top, 0.5); metal = _flat("ir_desk_frame", (0.75, 0.75, 0.76), 0.35, 0.8)
        div = _flat(f"ir_divider_{DIVIDER.index(self.div)}", self.div, 0.9); ped = _flat("ir_pedestal", (0.5, 0.5, 0.52), 0.4, 0.3)
        black = _flat("ir_black_metal", (0.03, 0.03, 0.03), 0.4, 1.0)
        tops, legs, peds, mons, scr, seats = [], [], [], [], [], []
        L = n * w
        for side in (1, -1):
            for k in range(n):
                y = -L / 2 + (k + 0.5) * w
                x = side * (d / 2 + 0.01)
                tops.append((x, y, 0.735, d, w - 0.01, 0.03))
                peds.append((x - side * 0.05, y + w / 2 - 0.25, 0.3, 0.55, 0.4, 0.58))
                # monitor arm clamped at the spine, one or two screens
                mons += [(side * 0.06, y, 0.95, 0.03, 0.03, 0.4), (side * 0.12, y, 1.1, 0.14, 0.025, 0.025)]
                for dy in ((-0.31, 0.31) if self.dual else (0.0,)):
                    scr.append((_screen(f"{i}_{len(scr)}", "desk"), (side * 0.19, y + dy, 1.1, 0.02, 0.58, 0.34)))      # one content image per monitor (A2: the same dashboard on every pod screen)
                    mons.append((side * 0.1775, y + dy, 1.1, 0.012, 0.6, 0.36))      # black back: the screen texture sat on both faces ('UI visible from behind', user 10-19)
                seats.append((side * (d + 0.45), y, math.atan2(0, -side)))
        for sx in (1, -1):                                       # end frames and a centre leg per pair
            for yy in (-L / 2 + 0.03, L / 2 - 0.03):
                legs.append((sx * (d / 2 + 0.01), yy, 0.36, d - 0.05, 0.04, 0.72))
        tray = [(0, 0, 0.6, 0.18, L - 0.1, 0.05)]                          # cable tray under the spine
        o = _parts_object(f"WorkstationPodFactory({i}).spawn_asset({i})",
                          [(top, tops), (metal, legs + tray), (div, [(0, 0, 0.98, 0.04, L, 0.46)]), (ped, peds), (black, mons)] + [(m_, [bx]) for m_, bx in scr])
        o["seats"] = [list(s) for s in seats]
        return o


class WallDisplayFactory:
    """Meeting-room display on the wall (front +X): a 65-75" panel and a camera bar under it. Origin at the bottom; mount at ~0.9 m."""
    def __init__(self, seed):
        self.W = random.Random(seed).choice((1.45, 1.66))

    def spawn_asset(self, i):
        black = _flat("ir_black_metal", (0.03, 0.03, 0.03), 0.4, 1.0); screen = _screen(i, "wall")
        W, H = self.W, self.W * 9 / 16
        return _parts_object(f"WallDisplayFactory({i}).spawn_asset({i})",
                             [(black, [(0, 0, 0.12 + H / 2, 0.05, W + 0.02, H + 0.02), (0.02, 0, 0.04, 0.05, 0.6, 0.06)]),
                              (screen, [(0.026, 0, 0.12 + H / 2, 0.005, W - 0.02, H - 0.02)])])


class WhiteboardFactory:
    """Wall whiteboard (front +X): white panel in an aluminium frame with a marker tray. Origin at the bottom; mount at ~0.9 m."""
    def __init__(self, seed):
        self.W = random.Random(seed).choice((1.5, 1.8))             # (1.2 m squashed the 16:9 writing)

    def spawn_asset(self, i):
        pw = _pick_print("whiteboard", i)                          # hand-written marker content: a blank board read as 'nobody works here'
        if pw is not None:                                         # by venue: 'DOCK SHIFT PLAN' hung in offices and pantries, 'SENSOR LOOP' in a clinic
            fv = set(globals().get("FLOOR_VENUES") or ()) | {VENUE}   # director's office (review 2026-10-17)
            ok = ((1, 2, 3, 5) if "warehouse" in fv else (1, 6) if fv & {"clinic-reception", "exam-room", "dental-room", "physio-room", "pharmacy"}
                  else (1, 4, 6) if fv & {"office", "open-office", "meeting-room"} else (1, 6))
            pool_ = [x for x in sorted(PRINT_ROOT.glob("whiteboard_*.png")) if int(x.stem.split("_")[1]) in ok]
            pw = pool_[zlib.crc32(f"whiteboard:{i}".encode()) % len(pool_)] if pool_ else pw
        white = _printed(pw, (0.93, 0.93, 0.92), 0.08) if pw is not None else _flat("ir_whiteboard", (0.93, 0.93, 0.92), 0.08)
        alu = _flat("ir_alu", (0.7, 0.7, 0.72), 0.3, 1.0)
        W, H = self.W, 1.0
        return _parts_object(f"WhiteboardFactory({i}).spawn_asset({i})",
                             [(white, [(0, 0, H / 2, 0.02, W, H)]),
                              (alu, [(0.005, 0, H, 0.03, W + 0.03, 0.025), (0.005, 0, 0.0, 0.03, W + 0.03, 0.025),
                                     (0.005, W / 2, H / 2, 0.03, 0.025, H), (0.005, -W / 2, H / 2, 0.03, 0.025, H),
                                     (0.04, 0, 0.0, 0.06, W * 0.6, 0.02)])])


class SpeakerphoneFactory:
    def __init__(self, seed):
        self.seed = seed

    def spawn_asset(self, i):
        import bmesh
        m = _flat("ir_black_metal", (0.03, 0.03, 0.03), 0.4, 1.0)
        bm = bmesh.new(); bmesh.ops.create_cone(bm, cap_ends=True, segments=24, radius1=0.12, radius2=0.1, depth=0.035)
        bmesh.ops.translate(bm, vec=(0, 0, 0.0175), verts=bm.verts)
        me = bpy.data.meshes.new(f"spk{i}"); bm.to_mesh(me); bm.free(); me.materials.append(m)
        o = bpy.data.objects.new(f"SpeakerphoneFactory({i}).spawn_asset({i})", me); bpy.context.scene.collection.objects.link(o)
        return o


class PaperStackFactory:
    """A4 paper / a document folder (critic r1: BookStackFactory on a meeting table reads as a home's books)."""
    def __init__(self, seed):
        r = random.Random(seed)
        self.h = r.uniform(0.004, 0.025); self.folder = r.random() < 0.4
        self.col = r.choice(((0.1, 0.18, 0.4), (0.05, 0.05, 0.05), (0.55, 0.08, 0.06)))

    def spawn_asset(self, i):
        pd = _pick_print("doc", i)
        paper = _printed(pd, (0.86, 0.86, 0.84), 0.7) if pd is not None else _flat("ir_paper", (0.86, 0.86, 0.84), 0.7)
        groups = [(paper, [(0, 0, self.h / 2, 0.297, 0.21, self.h)])]
        if self.folder:
            groups.append((_flat(f"ir_folder_{int(self.col[0] * 100)}", self.col, 0.5), [(0, 0, self.h + 0.0015, 0.31, 0.225, 0.003)]))
        return _parts_object(f"PaperStackFactory({i}).spawn_asset({i})", groups)


def _prims(name, groups):
    """Like _parts_object, with tilted boxes and cylinders: parts are ("box", (cx, cy, cz), (sx, sy, sz), (rx, ry, rz)) or
    ("cyl", (cx, cy, cz), (r_bottom, r_top, h), (rx, ry, rz)); rotations in radians about the part's centre. "rbox" is a box with
    rounded edges (upholstery: dental r20, the slab chair read as 'scattered planks')."""
    import bmesh
    from mathutils import Euler
    bm = bmesh.new(); bm.loops.layers.uv.verify()
    for slot, (mat, parts) in enumerate(groups):
        for kind, c, size, rot in parts:
            if kind == "rbox":                                   # bevelled in its own bmesh, then appended
                tb = bmesh.new(); bmesh.ops.create_cube(tb, size=1.0); bmesh.ops.scale(tb, vec=size, verts=tb.verts)
                bmesh.ops.bevel(tb, geom=list(tb.edges) + list(tb.verts), offset=min(size) * 0.4, segments=3, profile=0.5, affect="EDGES")
                bmesh.ops.rotate(tb, cent=(0, 0, 0), matrix=Euler(rot).to_matrix(), verts=tb.verts)
                bmesh.ops.translate(tb, vec=c, verts=tb.verts)
                for f in tb.faces:
                    f.material_index = slot; f.smooth = True
                tm = bpy.data.meshes.new("_rbox"); tb.to_mesh(tm); tb.free(); bm.from_mesh(tm); bpy.data.meshes.remove(tm)
                continue
            if kind == "box":
                r = bmesh.ops.create_cube(bm, size=1.0, calc_uvs=True)
                bmesh.ops.scale(bm, vec=size, verts=r["verts"])
                _face_uvs(bm, r["verts"])
            elif kind.startswith("bread:"):                      # real bread shapes (proc_bread.py): baguette / loaf / boule / roll / croissant / slice, sized like an lsph (semi-axes)
                from room_planner import proc_bread
                r = {"verts": proc_bread.build(bm, kind[6:], size, hash((round(c[0], 3), round(c[1], 3), round(c[2], 3))) & 0xFFFF)}
            elif kind == "lsph":                                 # a LOW-poly ellipsoid (80 faces, smooth shaded) for stocks of small items: buns, fruit
                r = bmesh.ops.create_icosphere(bm, subdivisions=2, radius=1.0)
                bmesh.ops.scale(bm, vec=size, verts=r["verts"])
            elif kind == "sph":                                  # ellipsoid with semi-axes `size`
                r = bmesh.ops.create_icosphere(bm, subdivisions=3, radius=1.0)   # 2 left the gym ball faceted (clinic r24)
                bmesh.ops.scale(bm, vec=size, verts=r["verts"])
            else:
                r = bmesh.ops.create_cone(bm, cap_ends=True, segments=20, radius1=size[0], radius2=size[1], depth=size[2])
            bmesh.ops.rotate(bm, cent=(0, 0, 0), matrix=Euler(rot).to_matrix(), verts=r["verts"])
            bmesh.ops.translate(bm, vec=c, verts=r["verts"])
            for f in {f for v in r["verts"] for f in v.link_faces}:
                f.material_index = slot; f.smooth = kind in ("sph", "lsph") or kind.startswith("bread:")     # a smooth ball (clinic r24: 'faceted, placeholder')
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    for mat, _ in groups:
        me.materials.append(mat)
    o = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(o)
    _bevel(o)
    return o


# ---- desk clutter (user 2026-10-16: 'the office is too clean, nobody's hands on it -- leftover snacks, books, pencils, cups') ------
_BRIGHT = ((0.75, 0.12, 0.1), (0.95, 0.65, 0.1), (0.1, 0.35, 0.7), (0.15, 0.55, 0.25), (0.85, 0.85, 0.82), (0.55, 0.15, 0.5))


class GloveBoxFactory:
    """A box of exam gloves (clinic r6 critic: 'no glove boxes, sanitizer or trays'): a coloured carton with a white tuft at its slot."""
    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        c = self.r.choice(((0.3, 0.35, 0.75), (0.55, 0.3, 0.65), (0.85, 0.85, 0.88), (0.2, 0.55, 0.6)))
        box = _flat(f"ir_glovebox_{int(c[0] * 100)}", c, 0.6); tuft = _flat("ir_glove_white", (0.92, 0.92, 0.95), 0.5)
        return _prims(f"GloveBoxFactory({i}).spawn_asset({i})", [(box, [("box", (0, 0, 0.035), (0.12, 0.24, 0.07), (0, 0, 0))]),
                                                                 (tuft, [("sph", (0, 0, 0.075), (0.03, 0.05, 0.015), (0, 0, 0))])])


class SanitizerFactory:
    """A pump bottle of hand sanitizer / soap: a clear or white bottle, a pump head with a nozzle."""
    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        c = self.r.choice(((0.85, 0.92, 0.95), (0.95, 0.95, 0.95), (0.6, 0.8, 0.9)))
        body = _flat(f"ir_sanitizer_{int(c[0] * 100)}", c, 0.15, transmission=0.4 if c[0] < 0.9 else 0.0)
        pump = _flat("ir_pump_white", (0.92, 0.92, 0.9), 0.4)
        return _prims(f"SanitizerFactory({i}).spawn_asset({i})",
                      [(body, [("cyl", (0, 0, 0.08), (0.035, 0.03, 0.16), (0, 0, 0))]),
                       (pump, [("cyl", (0, 0, 0.18), (0.012, 0.012, 0.05), (0, 0, 0)), ("box", (0.02, 0, 0.2), (0.05, 0.012, 0.012), (0, 0, 0))])])


class PaperTowelFactory:
    """A paper towel roll on an upright holder."""
    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        paper = _flat("ir_paper_towel", (0.94, 0.94, 0.92), 0.8); steel = _flat("ir_chrome", (0.8, 0.8, 0.82), 0.15, 1.0)
        return _prims(f"PaperTowelFactory({i}).spawn_asset({i})",
                      [(steel, [("cyl", (0, 0, 0.005), (0.08, 0.08, 0.01), (0, 0, 0)), ("cyl", (0, 0, 0.14), (0.008, 0.008, 0.28), (0, 0, 0))]),
                       (paper, [("cyl", (0, 0, 0.125), (0.06, 0.06, 0.22), (0, 0, 0))])])


class ClipboardFactory:
    """A clipboard with a form, lying flat: a hardboard back, a sheet, a metal clip."""
    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        board = _flat("ir_clipboard", (0.45, 0.32, 0.2), 0.6); pf = _pick_print("form", i)
        sheet = _printed(pf, (0.93, 0.93, 0.9), 0.7) if pf is not None else _flat("ir_paper", (0.93, 0.93, 0.9), 0.7)
        clip = _flat("ir_chrome", (0.8, 0.8, 0.82), 0.15, 1.0)
        return _prims(f"ClipboardFactory({i}).spawn_asset({i})",
                      [(board, [("box", (0, 0, 0.003), (0.23, 0.32, 0.006), (0, 0, 0))]),
                       (sheet, [("box", (0, -0.01, 0.0065), (0.21, 0.28, 0.001), (0, 0, 0))]),
                       (clip, [("box", (0, 0.145, 0.012), (0.08, 0.03, 0.012), (0, 0, 0))])])


class KidneyTrayFactory:
    """A stainless kidney dish with an instrument or two in it."""
    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        steel = _flat("ir_chrome", (0.8, 0.8, 0.82), 0.15, 1.0)
        return _prims(f"KidneyTrayFactory({i}).spawn_asset({i})",
                      [(steel, [("sph", (0, 0, 0.02), (0.07, 0.13, 0.02), (0, 0, 0)), ("box", (0.01, 0.02, 0.03), (0.008, 0.14, 0.004), (0, 0, 0.3))])])


class PenCupFactory:
    """A pen pot (mesh metal or ceramic) with 3-7 pencils/pens leaning in it."""
    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        r = self.r
        pot = _flat(f"ir_pencup_{r.randrange(3)}", r.choice(((0.15, 0.15, 0.16), (0.85, 0.84, 0.8), (0.6, 0.6, 0.62))), 0.4, 0.6)
        h = r.uniform(0.09, 0.11)
        sticks = []
        for k in range(r.randint(3, 7)):
            a = r.uniform(0, 2 * math.pi); t = r.uniform(0.08, 0.3); L = r.uniform(0.14, 0.18)
            sticks.append(("box", (0.015 * math.cos(a), 0.015 * math.sin(a), h * 0.4 + L / 2 * math.cos(t)), (0.007, 0.007, L),
                           (t * math.sin(a), -t * math.cos(a), 0)))
        col = _flat(f"ir_pencil_{r.randrange(len(_BRIGHT))}", r.choice(_BRIGHT), 0.5)
        return _prims(f"PenCupFactory({i}).spawn_asset({i})", [(pot, [("cyl", (0, 0, h / 2), (0.037, 0.04, h), (0, 0, 0))]), (col, sticks)])


class TakeawayCupFactory:
    """A paper coffee cup with a lid and a sleeve."""
    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        r = self.r
        paper = _flat("ir_cup_paper", r.choice(((0.92, 0.91, 0.88), (0.55, 0.38, 0.22))), 0.6)
        lid = _flat("ir_cup_lid", r.choice(((0.05, 0.05, 0.05), (0.92, 0.92, 0.92))), 0.4)
        sleeve = _flat("ir_cup_sleeve", (0.45, 0.3, 0.18), 0.8)
        return _prims(f"TakeawayCupFactory({i}).spawn_asset({i})",
                      [(paper, [("cyl", (0, 0, 0.065), (0.028, 0.042, 0.13), (0, 0, 0))]), (lid, [("cyl", (0, 0, 0.137), (0.044, 0.04, 0.014), (0, 0, 0))]),
                       (sleeve, [("cyl", (0, 0, 0.07), (0.037, 0.04, 0.05), (0, 0, 0))])])


class SnackFactory:
    """A snack: a chip/candy bag (half the time torn open, flattened), a biscuit box, or a few loose biscuits on a wrapper."""
    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        r = self.r
        col = _flat(f"ir_snack_{r.randrange(len(_BRIGHT))}", r.choice(_BRIGHT), 0.3, 0.4)
        kind = r.choice(("bag", "bag", "box", "loose"))
        if kind == "bag":
            opened = r.random() < 0.5
            parts = [("box", (0, 0, 0.02 if opened else 0.035), (0.16, 0.22, 0.04 if opened else 0.07), (0, 0, 0))]
            if opened:                                          # crumbs / chips spilled beside the torn bag
                crumb = _flat("ir_crumb", (0.85, 0.65, 0.3), 0.7)
                bits = [("box", (r.uniform(-0.1, 0.1), r.uniform(0.12, 0.18), 0.004), (0.03, 0.025, 0.006), (0, 0, r.uniform(0, 3))) for _ in range(r.randint(2, 5))]
                return _prims(f"SnackFactory({i}).spawn_asset({i})", [(col, parts), (crumb, bits)])
            return _prims(f"SnackFactory({i}).spawn_asset({i})", [(col, parts)])
        if kind == "box":
            return _prims(f"SnackFactory({i}).spawn_asset({i})", [(col, [("box", (0, 0, 0.025), (0.2, 0.08, 0.05), (0, 0, 0))])])
        wrap = _flat("ir_wrapper", (0.85, 0.85, 0.85), 0.3, 0.7); bisc = _flat("ir_biscuit", (0.72, 0.5, 0.25), 0.8)
        return _prims(f"SnackFactory({i}).spawn_asset({i})", [(wrap, [("box", (0, 0, 0.001), (0.18, 0.12, 0.002), (0, 0, 0.2))]),
                      (bisc, [("cyl", (r.uniform(-0.05, 0.05), r.uniform(-0.03, 0.03), 0.006 + 0.008 * k), (0.025, 0.025, 0.007), (0, 0, 0)) for k in range(r.randint(1, 3))])])


class PhoneFactory:
    """A smartphone lying face up (screen dark or lit)."""
    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        body = _flat("ir_phone_body", self.r.choice(((0.05, 0.05, 0.06), (0.8, 0.8, 0.82), (0.2, 0.3, 0.45))), 0.3, 0.6)
        scr = _flat("ir_pos_screen", (0.02, 0.03, 0.05), 0.15)
        return _prims(f"PhoneFactory({i}).spawn_asset({i})", [(body, [("box", (0, 0, 0.004), (0.072, 0.15, 0.008), (0, 0, 0))]),
                                                              (scr, [("box", (0, 0, 0.0085), (0.066, 0.142, 0.001), (0, 0, 0))])])


class NotebookFactory:
    """A notebook or A4 pad, closed or open, sometimes with sticky notes and a pen on it."""
    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        r = self.r
        cover = _flat(f"ir_notebook_{r.randrange(len(_BRIGHT))}", r.choice(_BRIGHT), 0.6)
        pn = _pick_print("nbpage", i)
        paper = _printed(pn, (0.86, 0.86, 0.84), 0.7) if pn is not None else _flat("ir_paper", (0.86, 0.86, 0.84), 0.7)
        w, h, t = r.choice(((0.15, 0.21, 0.012), (0.21, 0.297, 0.01)))
        groups = []
        if r.random() < 0.4:                                    # open: two pages side by side
            groups = [(cover, [("box", (0, 0, 0.002), (2 * w + 0.01, h + 0.01, 0.003), (0, 0, 0))]),
                      (paper, [("box", (-w / 2, 0, 0.006), (w, h, 0.006), (0, 0, 0)), ("box", (w / 2, 0, 0.006), (w, h, 0.006), (0, 0, 0))])]
        else:
            groups = [(paper, [("box", (0, 0, t / 2), (w - 0.004, h - 0.004, t), (0, 0, 0))]), (cover, [("box", (0, 0, t + 0.001), (w, h, 0.002), (0, 0, 0))])]
        if r.random() < 0.5:
            note = _flat("ir_sticky", r.choice(((0.98, 0.9, 0.3), (0.98, 0.6, 0.7), (0.6, 0.9, 0.6))), 0.7)
            groups.append((note, [("box", (r.uniform(-0.04, 0.04), r.uniform(-0.06, 0.06), t + 0.004), (0.076, 0.076, 0.002), (0, 0, r.uniform(-0.4, 0.4)))]))
        if r.random() < 0.5:
            pen = _flat("ir_black_metal", (0.03, 0.03, 0.03), 0.4, 1.0)
            groups.append((pen, [("box", (0.02, 0, t + 0.008), (0.009, 0.14, 0.009), (0, 0, r.uniform(-0.6, 0.6)))]))
        return _prims(f"NotebookFactory({i}).spawn_asset({i})", groups)


class OfficeDeskFactory:
    """A private-office desk (front +X = the user's side): 1.4-1.8 x 0.75-0.85 m top on panel legs with a modesty panel, a drawer
    pedestal, a monitor on a stand and a keyboard (critic r3: an ABO 'desk' read as a low cabinet with a monitor on it)."""
    COMPACT = False

    def __init__(self, seed):
        r = random.Random(seed)
        self.L = r.choice((1.4, 1.6, 1.8)); self.D = r.uniform(0.75, 0.85)
        self.top = r.choice(((0.88, 0.87, 0.84), (0.45, 0.32, 0.2), (0.62, 0.5, 0.36), (0.2, 0.2, 0.2)))
        self.dual = r.random() < 0.35
        if OfficeDeskFactory.COMPACT:                           # a small private office / phone booth (realize._make sets it from the room size): 1.0 x 0.5 m, no second monitor (O4: 1.9 x 1.4 m free area, 'not placed office_desk')
            self.L, self.D, self.dual = 1.0, 0.5, False
        self.oak = STYLE.get("desk_style") in ("oak", "frame")  # kit: natural oak desks (B refs: 'two OAK workstations'); 'frame' = timber top on a BLACK steel frame (J office ref)
        self.frame = STYLE.get("desk_style") == "frame"
        if self.oak:
            self.top = (0.72, 0.55, 0.34)

    def spawn_asset(self, i):
        L, D = self.L, self.D
        oak = getattr(self, "oak", False)
        top = _flat(f"ir_desk_top_{int(self.top[0] * 100)}", self.top, 0.45, wood=oak); panel = _flat("ir_desk_panel", (0.3, 0.3, 0.31), 0.5, 0.2) if not oak else (_flat("ir_desk_panel_frame", (0.04, 0.04, 0.045), 0.45, 0.9) if getattr(self, "frame", False) else _flat("ir_desk_panel_oak", (0.72, 0.55, 0.34), 0.45, wood=True))
        ped = _flat("ir_pedestal", (0.5, 0.5, 0.52), 0.4, 0.3) if not oak else (_flat("ir_pedestal_black", (0.05, 0.05, 0.055), 0.45, 0.9) if getattr(self, "frame", False) else _flat("ir_pedestal_oak", (0.66, 0.5, 0.3), 0.45, wood=True)); black = _flat("ir_black_metal", (0.03, 0.03, 0.03), 0.4, 1.0)
        screen = _screen(i, "desk")
        # Anchor the complete monitor assembly to the actual 0.735+0.03/2 tabletop.
        # The legacy base at0.82 floated64mm above it; retain relative assembly geometry.
        monitor_dz = (0.735 + 0.03 / 2 + 0.012 / 2) - 0.82
        mons = [(-D / 2 + 0.15, 0, 0.82 + monitor_dz, 0.18, 0.22, 0.012), (-D / 2 + 0.17, 0, 0.92 + monitor_dz, 0.03, 0.05, 0.2)]
        scr = [(-D / 2 + 0.19, dy, 1.08 + monitor_dz, 0.02, 0.56, 0.33) for dy in ((-0.29, 0.29) if self.dual else (0.0,))]
        mons += [(-D / 2 + 0.2025, dy, 1.08 + monitor_dz, 0.012, 0.58, 0.35) for dy in ((-0.29, 0.29) if self.dual else (0.0,))]      # black back toward the visitor side
        return _parts_object(f"OfficeDeskFactory({i}).spawn_asset({i})",
                             [(top, [(0, 0, 0.735, D, L, 0.03)]),
                              (panel, [(0, sy * (L / 2 - 0.02), 0.36, D - 0.04, 0.03, 0.72) for sy in (1, -1)] + [(-D / 2 + 0.06, 0, 0.45, 0.02, L - 0.08, 0.45)]),
                              (ped, [(0.0, L / 2 - 0.27, 0.32, 0.55, 0.42, 0.6)]),
                              (black, mons + [(0.08, 0, 0.755, 0.15, 0.44, 0.015)]), (screen, scr)])


class FilingCabinetFactory:
    """Steel office filing cabinet (front +X): a 2-4 drawer lateral or vertical filer with recessed pulls (critic r3-r5: ABO 'filing'
    pools kept returning wooden dressers and nightstands)."""
    def __init__(self, seed):
        r = random.Random(seed)
        self.lateral = r.random() < 0.5; self.n = r.choice((2, 3, 4)) if self.lateral else r.choice((3, 4))
        self.c = r.choice(((0.82, 0.82, 0.8), (0.55, 0.56, 0.57), (0.18, 0.18, 0.19)))

    def spawn_asset(self, i):
        W, D = (0.9, 0.5) if self.lateral else (0.47, 0.62)
        H = 0.36 * self.n + 0.05
        body = _flat(f"ir_filer_{int(self.c[0] * 100)}", self.c, 0.35, 0.6); pull = _flat("ir_black_metal", (0.03, 0.03, 0.03), 0.4, 1.0)
        gaps = [(D / 2 + 0.001, 0, 0.05 + k * 0.36, 0.002, W - 0.02, 0.006) for k in range(1, self.n)]
        pulls = [(D / 2 + 0.008, 0, 0.05 + (k + 0.75) * 0.36, 0.012, W * 0.45, 0.025) for k in range(self.n)]
        if os.environ.get("ROOM_FILER_DETAIL") == "1":                         # O4 external review: 'uniform grey, weak drawer gaps, no handle shading' -> a carcass with a 3 mm reveal between separate drawer fronts, recessed pull pockets with a bar inside, powder coat with orange peel
            nt = body.node_tree
            if not body.get("ir_peel"):
                N, L = nt.nodes, nt.links; b = N["Principled BSDF"]; tc = N.new("ShaderNodeTexCoord"); nz = N.new("ShaderNodeTexNoise"); nz.inputs["Scale"].default_value = 700.0; nz.inputs["Detail"].default_value = 1.0
                L.new(tc.outputs["Object"], nz.inputs["Vector"]); bp = N.new("ShaderNodeBump"); bp.inputs["Strength"].default_value = 0.08; bp.inputs["Distance"].default_value = 0.0004; L.new(nz.outputs["Fac"], bp.inputs["Height"]); L.new(bp.outputs["Normal"], b.inputs["Normal"])
                b.inputs["Metallic"].default_value = 0.0; b.inputs["Roughness"].default_value = 0.4; body["ir_peel"] = True
                sc_ = N.new("ShaderNodeTexNoise"); sc_.inputs["Scale"].default_value = 6.0; sc_.inputs["Detail"].default_value = 5.0; L.new(tc.outputs["Object"], sc_.inputs["Vector"])          # a soft, low-contrast patchy wear: scuffs / hand-grime a little rougher and darker (+-4 %)
                rr = N.new("ShaderNodeMapRange"); rr.inputs["To Min"].default_value = 0.36; rr.inputs["To Max"].default_value = 0.52; L.new(sc_.outputs["Fac"], rr.inputs["Value"]); L.new(rr.outputs["Result"], b.inputs["Roughness"])
                ao_ = N.new("ShaderNodeAmbientOcclusion"); ao_.inputs["Distance"].default_value = 0.05; mxc = N.new("ShaderNodeMix"); mxc.data_type = "RGBA"; mxc.blend_type = "MULTIPLY"; mxc.inputs["Factor"].default_value = 0.5
                mxc.inputs[6].default_value = tuple(self.c) + (1.0,); mxc.inputs[7].default_value = (0.7, 0.7, 0.7, 1.0); L.new(ao_.outputs["AO"], mxc.inputs["Factor"]); L.new(mxc.outputs[2], b.inputs["Base Color"])
            dh = (H - 0.05) / self.n; fronts, recess, bars = [], [], []
            for k in range(self.n):
                z0 = 0.05 + k * dh
                fronts.append((D / 2 + 0.006, 0, z0 + dh / 2, 0.012, W - 0.016, dh - 0.006))                      # a drawer front 3 mm shy of its neighbours
                recess.append((D / 2 + 0.013, 0, z0 + dh * 0.78, 0.004, W * 0.42, 0.032))                           # the pull pocket (dark)
                bars.append((D / 2 + 0.012, 0, z0 + dh * 0.78 - 0.004, 0.012, W * 0.4, 0.008))                    # the bar inside it
            lab = _flat("ir_filer_label", (0.93, 0.92, 0.86), 0.6); lock = _flat("ir_filer_lock", (0.7, 0.7, 0.72), 0.25, 1.0)
            labels = [(D / 2 + 0.0125, -W * 0.3, 0.05 + k * dh + dh * 0.55, 0.003, W * 0.2, 0.05) for k in range(self.n)]          # a paper label in a frame on every drawer
            frames = [(D / 2 + 0.0118, -W * 0.3, 0.05 + k * dh + dh * 0.55, 0.002, W * 0.22, 0.062) for k in range(self.n)]
            feet = [(0, sy * (W / 2 - 0.03), 0.025, D - 0.06, 0.04, 0.05) for sy in (1, -1)]                              # a recessed plinth: two feet
            top = [(0, 0, H + 0.004, D + 0.012, W + 0.012, 0.012)]                                                        # a top plate overhanging 6 mm
            return _parts_object(f"FilingCabinetFactory({i}).spawn_asset({i})", [(body, [(0, 0, H / 2 + 0.03, D - 0.004, W, H - 0.05)] + fronts + top), (pull, recess + frames + feet), (_flat("ir_filer_bar", (0.62, 0.63, 0.65), 0.3, 1.0), bars), (lab, labels), (lock, [(D / 2 + 0.0135, W * 0.38, 0.05 + dh * (self.n - 0.35), 0.003, 0.016, 0.016)])])
        return _parts_object(f"FilingCabinetFactory({i}).spawn_asset({i})", [(body, [(0, 0, H / 2, D, W, H)]), (pull, gaps + pulls)])


# ---- clinics and shops (non-home 20, 2026-10-16) -----------------------------------------------------------------------------------
class ReceptionDeskFactory:
    """Reception / pharmacy desk (front +X = the visitor side): a work surface at 0.75 m behind a 1.1 m transaction ledge, a modesty
    front, a monitor on the staff side. 2.0-3.2 m long."""
    def __init__(self, seed):
        r = random.Random(seed)
        self.L = r.choice((2.0, 2.4, 2.8, 3.2)); self.front = r.choice(((0.9, 0.9, 0.88), (0.35, 0.45, 0.55)) if VENUE == "clinic-reception"
                                                                      else ((0.9, 0.9, 0.88), (0.62, 0.5, 0.36), (0.35, 0.45, 0.55)))   # no wood in a clinic (r23)

    def spawn_asset(self, i):
        L = self.L
        acc = STYLE.get("accent_rgb")                           # kit accent (S16 pharmacy): a white counter with a green base strip and a warm light strip under the top
        if acc:
            self.front = (0.92, 0.92, 0.9)
        front = _flat(f"ir_reception_front_{int(self.front[2] * 100)}", self.front, 0.5); top = _flat("ir_counter_top_white_stone", (0.86, 0.85, 0.82), 0.25)
        work = _flat("ir_desk_top_88", (0.88, 0.87, 0.84), 0.45); black = _flat("ir_black_metal", (0.03, 0.03, 0.03), 0.4, 1.0)
        screen = _screen(i, "desk")
        # End returns stop2mm short of the front: avoid20mm coplanar overlap.
        side_x0, side_x1 = -0.33, 0.33 - 0.04 / 2 - 0.002
        # Anchor the full display assembly to the actual0.760m staff worktop.
        monitor_dz = (0.745 + 0.03 / 2 + 0.012 / 2) - 0.82
        return _parts_object(f"ReceptionDeskFactory({i}).spawn_asset({i})",
                             [(front, [(0.33, 0, 0.55, 0.04, L, 1.1)] + [((side_x0 + side_x1) / 2, sy * (L / 2 - 0.02), 0.37, side_x1 - side_x0, 0.04, 0.74) for sy in (1, -1)]),
                              (top, [(0.3, 0, 1.115, 0.3, L + 0.04, 0.03)]), (work, [(-0.05, 0, 0.745, 0.7, L - 0.04, 0.03)]),
                              (black, [(-0.2, -L / 4, 0.82 + monitor_dz, 0.2, 0.22, 0.012), (-0.2, -L / 4, 0.92 + monitor_dz, 0.03, 0.05, 0.2), (-0.1675, -L / 4, 1.07 + monitor_dz, 0.012, 0.56, 0.34)]),
                              (screen, [(-0.18, -L / 4, 1.07 + monitor_dz, 0.02, 0.54, 0.32)])] + ([(_flat("ir_accent_strip", tuple(acc), 0.45), [(0.356, 0, 0.09, 0.012, L, 0.18)]),
                              (_glow_strip(), [(0.356, 0, 1.06, 0.01, L - 0.1, 0.025)])] if acc else []))


def _glow_strip():
    m = _flat("ir_counter_glow", (1.0, 0.95, 0.85), 0.4); gb = m.node_tree.nodes["Principled BSDF"]
    gb.inputs["Emission Color"].default_value = (1.0, 0.93, 0.8, 1); gb.inputs["Emission Strength"].default_value = 4.0
    return m


class WaitingBenchFactory:
    """Beam seating (front +X): 3-5 moulded seats on a steel beam with two legs -- waiting rooms line these up along walls."""
    def __init__(self, seed):
        r = random.Random(seed)
        self.n = r.choice((3, 4, 4, 5))   # one seat colour per room (clinic r27: 'teal and charcoal rows mixed', 2 of 3); no salmon (r16)
        if VENUE == "pharmacy" and STYLE.get("accent_rgb"):       # pharmacy ref: moulded green benches along the window wall
            self.c = tuple(STYLE.get("band_rgb") or (0.4, 0.6, 0.22))
        else:
            self.c = _ROOM_PICK.setdefault("waiting_bench", r.choice(((0.15, 0.35, 0.55), (0.12, 0.12, 0.13), (0.2, 0.4, 0.42), (0.55, 0.25, 0.15))))   # no light grey: 'white benches, white desk, white walls' (floor D3 r11)

    def spawn_asset(self, i):
        n, w = self.n, 0.56
        L = n * w
        seat = _flat(f"ir_bench_seat_{int(self.c[2] * 100)}", self.c, 0.45); steel = _flat("ir_desk_frame", (0.75, 0.75, 0.76), 0.35, 0.8)
        seats = [(0.0, -L / 2 + (k + 0.5) * w, 0.45, 0.46, w - 0.06, 0.05) for k in range(n)]
        backs = [(-0.22, -L / 2 + (k + 0.5) * w, 0.68, 0.04, w - 0.08, 0.4) for k in range(n)]
        frame = [(-0.05, 0, 0.4, 0.06, L, 0.05)] + [(-0.05, sy * (L / 2 - 0.15), 0.2, 0.05, 0.05, 0.4) for sy in (1, -1)]
        frame += [(-0.05, sy * (L / 2 - 0.15), 0.01, 0.5, 0.06, 0.02) for sy in (1, -1)]
        return _parts_object(f"WaitingBenchFactory({i}).spawn_asset({i})", [(seat, seats + backs), (steel, frame)])


class WaterCoolerFactory:
    """A waiting-room water cooler (front +X): white cabinet, a blue bottle on top, two taps, a cup dispenser."""
    def __init__(self, seed):
        self.seed = seed

    def spawn_asset(self, i):
        body = _flat("ir_ac_white", (0.86, 0.86, 0.85), 0.4); bottle = _flat("ir_cooler_bottle", (0.35, 0.6, 0.85), 0.05, transmission=0.8)
        blk = _flat("ir_black_plastic", (0.04, 0.04, 0.045), 0.5)
        return _prims(f"WaterCoolerFactory({i}).spawn_asset({i})", [
            (body, [("box", (0, 0, 0.5), (0.32, 0.32, 1.0), (0, 0, 0)), ("cyl", (0.06, 0.2, 0.9), (0.035, 0.035, 0.25), (0, 0, 0))]),
            (bottle, [("cyl", (0, 0, 1.2), (0.13, 0.13, 0.38), (0, 0, 0))]),
            (blk, [("box", (0.17, sy * 0.05, 0.82), (0.03, 0.025, 0.03), (0, 0, 0)) for sy in (1, -1)])])


class OperatorStoolFactory:
    """Dentist's operator stool (front +X): a round upholstered saddle seat on a gas column and five-star base, a small back rest
    (dental r10: 'a black high-back office task chair for the clinician', 3 of 3)."""
    def __init__(self, seed):
        self.c = random.Random(seed).choice(((0.05, 0.25, 0.5), (0.03, 0.35, 0.38), (0.15, 0.15, 0.17)))

    def spawn_asset(self, i):
        fab = _flat(f"ir_stool_{int(self.c[1] * 100)}", self.c, 0.5); blk = _flat("ir_black_plastic", (0.04, 0.04, 0.045), 0.5)
        steel = _flat("ir_chrome", (0.8, 0.8, 0.82), 0.15, 1.0)
        spokes = [("box", (0.14 * math.cos(a), 0.14 * math.sin(a), 0.06), (0.28, 0.035, 0.03), (0, 0, a)) for a in [k * 2 * math.pi / 5 for k in range(5)]]
        return _prims(f"OperatorStoolFactory({i}).spawn_asset({i})", [(blk, spokes), (steel, [("cyl", (0, 0, 0.3), (0.025, 0.025, 0.46), (0, 0, 0)),
                      ("cyl", (-0.2, 0, 0.72), (0.012, 0.012, 0.22), (0, 0, 0))]),
                      (fab, [("cyl", (0, 0, 0.56), (0.22, 0.2, 0.08), (0, 0, 0)), ("rbox", (-0.22, 0, 0.84), (0.05, 0.3, 0.12), (0, 0, 0))])])


class ClinicLowTableFactory:
    """Waiting-room low table (front +X): white laminate top on a chrome frame (floor D3/F3 r8: 'a residential wooden coffee table')."""
    def __init__(self, seed):
        self.L = random.Random(seed).choice((1.0, 1.2))

    def spawn_asset(self, i):
        L, W, H = self.L, 0.55, 0.42
        top = _flat("ir_laminate_white", (0.88, 0.88, 0.86), 0.35); steel = _flat("ir_desk_frame", (0.75, 0.75, 0.76), 0.35, 0.8)
        legs = [("box", (sx * (W / 2 - 0.04), sy * (L / 2 - 0.04), H / 2 - 0.015), (0.03, 0.03, H - 0.03), (0, 0, 0)) for sx in (1, -1) for sy in (1, -1)]
        # magazines fanned on the top and a leaflet pile on the shelf: a book_stack read as 'a tall pile of hardbacks, residential'
        # (floor F3 r13, 3 of 3)
        r = random.Random(int(L * 1000) + i)
        mags = [(_flat(f"ir_magazine_{k}", c, 0.45), [("box", (r.uniform(-0.08, 0.08), y, H + 0.004 + 0.004 * k), (0.21, 0.28, 0.004), (0, 0, r.uniform(-0.5, 0.5)))])
                for k, (y, c) in enumerate(zip((-L / 4, -L / 4 + 0.12, L / 4, L / 4 + 0.1),
                                               ((0.75, 0.2, 0.2), (0.15, 0.4, 0.7), (0.9, 0.75, 0.2), (0.2, 0.55, 0.35))))]
        return _prims(f"ClinicLowTableFactory({i}).spawn_asset({i})", [(top, [("box", (0, 0, H - 0.015), (W, L, 0.03), (0, 0, 0))]),
                                                                      (steel, legs + [("box", (0, 0, 0.12), (W - 0.1, L - 0.1, 0.015), (0, 0, 0))]),
                                                                      (_flat("ir_leaflets", (0.92, 0.92, 0.9), 0.6), [("box", (0, 0.1, 0.15), (0.21, 0.3, 0.04), (0, 0, 0))])]
                      + mags)


class PrepTableFactory:
    """Café back-kitchen prep station (front +X): a stainless table with an upstand, a sink bowl and tap at one end, an undershelf of
    containers, a cutting board, gastronorm pans and a plate stack on top (floor H r19: 'an office tea point, no prep or wash-up', 3 of 3)."""
    def __init__(self, seed):
        self.L = random.Random(seed).choice((1.5, 1.8))

    def spawn_asset(self, i):
        L, W, H = self.L, 0.7, 0.9
        st = _flat("ir_stainless", (0.72, 0.73, 0.74), 0.3, 0.9); dark = _flat("ir_sink_gap", (0.08, 0.08, 0.09), 0.5)
        board = _flat("ir_cutting_board", (0.92, 0.9, 0.84), 0.6); tub = _flat("ir_food_tub", (0.94, 0.94, 0.92), 0.4)
        lid = _flat("ir_tub_lid", (0.2, 0.45, 0.75), 0.5); plate = _flat("ir_plate_white", (0.95, 0.95, 0.94), 0.25)
        sy = -L / 2 + 0.3                                        # sink end
        legs = [("box", (sx * (W / 2 - 0.04), sy_ * (L / 2 - 0.04), H / 2), (0.04, 0.04, H), (0, 0, 0)) for sx in (1, -1) for sy_ in (1, -1)]
        return _prims(f"PrepTableFactory({i}).spawn_asset({i})", [
            (st, legs + [("box", (0, 0, H - 0.02), (W, L, 0.04), (0, 0, 0)), ("box", (-W / 2 + 0.01, 0, H + 0.1), (0.02, L, 0.2), (0, 0, 0)),
                         ("box", (0, 0, 0.2), (W - 0.06, L - 0.06, 0.02), (0, 0, 0)),
                         ("box", (0, sy, H - 0.16), (0.46, 0.46, 0.3), (0, 0, 0)),                                    # bowl
                         ("box", (-W / 2 + 0.08, sy, H + 0.2), (0.04, 0.04, 0.4), (0, 0, 0)),                         # tap riser
                         ("box", (-W / 2 + 0.2, sy, H + 0.4), (0.26, 0.035, 0.035), (0, 0, 0)),                       # spout
                         ("box", (0.02, 0.35, H + 0.05), (0.32, 0.26, 0.1), (0, 0, 0)),                                # gastronorm pans
                         ("box", (0.02, 0.08, H + 0.05), (0.32, 0.26, 0.1), (0, 0, 0))]),
            (dark, [("box", (0, sy, H + 0.001), (0.4, 0.4, 0.004), (0, 0, 0)), ("box", (0.02, 0.35, H + 0.101), (0.28, 0.22, 0.002), (0, 0, 0))]),
            (board, [("box", (0.05, L / 2 - 0.3, H + 0.015), (0.35, 0.45, 0.025), (0, 0, 0.1))]),
            (plate, [("cyl", (-0.1, L / 2 - 0.12, H + 0.06), (0.24, 0.24, 0.12), (0, 0, 0))]),
            (tub, [("box", (0.0, y, 0.21 + 0.13), (0.4, 0.3, 0.26), (0, 0, 0)) for y in (-L / 4, L / 4)]),
            (lid, [("box", (0.0, y, 0.21 + 0.27), (0.42, 0.32, 0.02), (0, 0, 0)) for y in (-L / 4, L / 4)])])


class PalletRackFactory:
    """Heavy pallet racking, one 2.7 m bay (front +X): blue frames, orange beams at three levels, a pallet of cartons on every level
    (floor J r13-r15: 'only 2 m boltless shelving under a 5 m roof -- a big stockroom, not a warehouse', 3 of 3)."""
    def __init__(self, seed, H=4.0):                           # three levels, top load ~4.1 m: the hall walls are 4.8-5.4 m
        self.r = random.Random(seed); self.H = H

    def spawn_asset(self, i):
        r, H, L, D = self.r, self.H, 2.7, 1.1
        blue = _flat("ir_rack_blue", (0.05, 0.16, 0.42), 0.45, 0.6); orange = _flat("ir_rack_orange", (0.85, 0.32, 0.04), 0.45, 0.6)
        if os.environ.get("ROOM_RACK_BARE_METAL") == "1":
            blue, orange = _zinc(i), _zinc(i + 2)
        wood = _flat("ir_pallet_wood", (0.55, 0.42, 0.26), 0.8); card = _flat("ir_carton", (0.62, 0.46, 0.28), 0.85)
        wrap = _flat("ir_stretch_wrap", (0.8, 0.82, 0.84), 0.25, transmission=0.3)
        posts = [("box", (sx * (D / 2 - 0.04), sy * (L / 2 - 0.04), H / 2), (0.08, 0.08, H), (0, 0, 0)) for sx in (1, -1) for sy in (1, -1)]
        braces = [("box", (0, sy * (L / 2 - 0.04), z), (D - 0.1, 0.03, 0.03), (0, 0, 0)) for sy in (1, -1) for z in (0.4, 1.6, 2.8, 4.0) if z < H]
        levels = [0.0, 1.45, 2.9] + ([4.1] if H > 4.3 else [])
        beams = [("box", (sx * (D / 2 - 0.04), 0, z), (0.05, L - 0.1, 0.12), (0, 0, 0)) for sx in (1, -1) for z in levels[1:]]
        pal, box, wr = [], [], []
        for z in levels:
            z0 = z + (0.06 if z > 0 else 0.0)
            for y in (-0.62, 0.62):
                pal.append(("box", (0, y, z0 + 0.07), (1.0, 1.15, 0.14), (0, 0, 0)))
                h = r.uniform(0.5, 1.0) if z < levels[-1] else r.uniform(0.5, 0.9)      # the top tier was 0.3-0.6 m: it read emptier than the lower ones (J r44)
                if r.random() < float(STYLE.get("rack_load") or 0.97):          # was 0.85: one pallet position in seven bare read as 'racks with empty bays' (J r43/r44 CNT-04); kit rack_load to override
                    box.append(("box", (0, y, z0 + 0.14 + h / 2), (0.95, 1.1, h), (0, 0, 0)))
                    if r.random() < 0.5:
                        wr.append(("box", (0, y, z0 + 0.14 + h / 2), (0.97, 1.12, h + 0.01), (0, 0, 0)))
        return _prims(f"PalletRackFactory({i}).spawn_asset({i})", [(blue, posts + braces), (orange, beams), (wood, pal), (card, box)] + ([(wrap, wr)] if wr else []))


class UrinalFactory:
    """Two wall-hung urinals with a privacy divider between them (front +X, back on the wall): the second restroom of a café floor
    becomes the gents' -- two identical single WCs with half the room bare read as 'oversized, unfinished copies' (floor H r31, 3 of 3)."""
    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        D = 0.42; xb = -D / 2
        cer = _flat("ir_ceramic_white", (0.93, 0.93, 0.92), 0.12); chrome = _flat("ir_chrome", (0.8, 0.8, 0.82), 0.15, 1.0)
        div = _flat("ir_urinal_divider", (0.62, 0.64, 0.66), 0.35)
        hole = _flat("ir_urinal_bowl", (0.55, 0.57, 0.58), 0.2)
        bowls, pipes, holes = [], [], []
        for y in (-0.38, 0.38):
            bowls += [("rbox", (xb + 0.17, y, 0.85), (0.32, 0.38, 0.66), (0, 0, 0))]
            holes += [("rbox", (xb + 0.31, y, 0.8), (0.05, 0.26, 0.42), (0, 0, 0))]   # the dark bowl opening: plain white boxes on a
            # steel sheet read as 'two dispensers on a floating panel' (floor J r22, 2 of 3)
            pipes += [("cyl", (xb + 0.05, y, 1.35), (0.016, 0.016, 0.34), (0, 0, 0)), ("box", (xb + 0.06, y, 1.53), (0.06, 0.08, 0.06), (0, 0, 0)),
                      ("cyl", (xb + 0.08, y, 0.26), (0.022, 0.022, 0.52), (0, 0, 0))]   # waste pipe to the floor: the placer sets the
            # lowest point on the floor, and without it the wall-hung bowls sank (floor H r32)
        panel = [("box", (xb + 0.21, 0.0, 1.0), (0.4, 0.025, 0.8), (0, 0, 0))]
        return _prims(f"UrinalFactory({i}).spawn_asset({i})", [(cer, bowls), (chrome, pipes), (div, panel), (hole, holes)])


class RollerShutterFactory:
    """A loading-dock roller shutter on a hall wall (front +X, back on the wall): grey steel slats in side guides under a coil box, a
    yellow-black hazard strip on the floor and two yellow bollards (floor J r18: 'no dock or roller door -- a big stockroom', 3 of 3)."""
    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        D, W, H = 0.5, 3.6, 4.0
        steel = _flat("ir_shutter_steel", (0.5, 0.52, 0.54), 0.4, 0.8); dark = _flat("ir_shutter_guide", (0.18, 0.19, 0.2), 0.45, 0.7)
        yel = _flat("ir_hazard_yellow", (0.85, 0.62, 0.02), 0.5); blk = _flat("ir_ink", (0.05, 0.05, 0.06), 0.6)
        xb = -D / 2
        z0 = float(STYLE.get("shutter_open") or 0.0) * H                      # kit shutter_open=0..1: the slats are raised by this fraction of the opening (J r42 LAY-01: 'a loading shutter fully down across the opening')
        slats = [("box", (xb + 0.03, 0, (z0 + H) / 2), (0.03, W, H - z0), (0, 0, 0))] + \
                [("box", (xb + 0.05, 0, z0 + 0.1 + k * 0.13), (0.015, W, 0.035), (0, 0, 0)) for k in range(int((H - z0 - 0.2) / 0.13))]
        guides = [("box", (xb + 0.06, s * (W / 2 + 0.06), (H + 0.3) / 2), (0.12, 0.12, H + 0.3), (0, 0, 0)) for s in (1, -1)] + \
                 [("box", (xb + 0.18, 0, H + 0.3), (0.36, W + 0.3, 0.45), (0, 0, 0))]
        haz = [("box", (xb + 0.35, 0, 0.003), (0.3, W, 0.006), (0, 0, 0))]
        stripes = [("box", (xb + 0.35, -W / 2 + 0.15 + k * 0.3, 0.0065), (0.3, 0.12, 0.002), (0, 0, 0.6)) for k in range(int(W / 0.3))]
        bollards = [("cyl", (xb + 0.4, s * (W / 2 + 0.25), 0.55), (0.08, 0.08, 1.1), (0, 0, 0)) for s in (1, -1)]
        void = [("box", (xb + 0.012, 0, z0 / 2), (0.01, W - 0.02, z0), (0, 0, 0))] if z0 > 0.2 else []      # a raised shutter shows the dark dock opening below it (J r44: 'still reads as a fully closed grey panel')
        vm = _flat("ir_dock_void", (0.025, 0.027, 0.03), 0.9)
        return _prims(f"RollerShutterFactory({i}).spawn_asset({i})", [(steel, slats), (dark, guides), (yel, haz + bollards), (blk, stripes)] + ([(vm, void)] if void else []))


class ExamTableFactory:
    """Examination / treatment couch (front +X): padded top at 0.7 m with a raised head section, a cabinet base, a paper roll, a step."""
    def __init__(self, seed):
        r = random.Random(seed)
        self.c = r.choice(((0.03, 0.12, 0.2), (0.03, 0.03, 0.035), (0.02, 0.15, 0.16), (0.06, 0.08, 0.2)))  # deep vinyl: pale pads vanished (r5, r8)
        if STYLE.get("upholstery_rgb"):                           # the kit's vinyl colour (S20: sage-teal beds; the random navy ignored it)
            self.c = tuple(STYLE["upholstery_rgb"])

    def spawn_asset(self, i):
        # a couch, not a cabinet (clinic r6: 'a white box with a grey slab'): a narrow inset plinth on a steel frame with open space
        # around it, a thick padded top overhanging it, the head section raised 30 deg, a paper roll and a step
        pad = _flat(f"ir_exam_pad_{int(self.c[2] * 100)}", self.c, 0.55); base = _flat("ir_pantry_cab_90", (0.9, 0.9, 0.88), 0.45)
        paper = _flat("ir_paper", (0.93, 0.93, 0.9), 0.7); steel = _flat("ir_desk_frame", (0.75, 0.75, 0.76), 0.35, 0.8)
        hy, hz = 0.45, 0.72                                      # head hinge (local y) and top height
        o = _prims(f"ExamTableFactory({i}).spawn_asset({i})",
                      [(base, ([] if STYLE.get("exam_frame") == "steel" else [("box", (0, -0.1, 0.33), (0.4, 0.9, 0.5), (0, 0, 0))]) + [("box", (0.45, -0.35, 0.11), (0.28, 0.42, 0.22), (0, 0, 0))]),
                       (steel, ([("cyl", (sx * 0.24, -0.1 + sy * 0.55, 0.33), (0.022, 0.022, 0.56), (0, 0, 0)) for sx in (1, -1) for sy in (1, -1)]       # kit exam_frame 'steel': an open steel frame on 4 rollers (S18 A/B: 'square box base, ref: metal frame + rollers')
                                + [("sph", (sx * 0.24, -0.1 + sy * 0.55, 0.04), (0.035, 0.035, 0.035), (0, 0, 0)) for sx in (1, -1) for sy in (1, -1)] if STYLE.get("exam_frame") == "steel" else []) +
                               [("box", (0, -0.1, 0.03), (0.55, 1.3, 0.04), (0, 0, 0)), ("box", (0, -0.1, 0.62), (0.5, 1.2, 0.05), (0, 0, 0)),
                                ("cyl", (0, -0.98, 0.7), (0.05, 0.05, 0.56), (0, math.pi / 2, math.pi / 2))]),
                       (pad, [("box", (0, -0.2, hz), (0.68, 1.3, 0.12), (0, 0, 0)),
                              ("box", (0, hy + 0.3 * math.cos(0.52), hz + 0.3 * math.sin(0.52)), (0.68, 0.62, 0.12), (0.52, 0, 0))]),
                       (_flat("ir_pillow_white", (0.95, 0.95, 0.93), 0.9), [("box", (0, hy + 0.2, hz + 0.19), (0.36, 0.26, 0.08), (0.52, 0, 0))]),    # a pillow on the raised head section
                       (paper, [("box", (0, -0.35, hz + 0.062), (0.4, 0.9, 0.003), (0, 0, 0)),   # a strip: a full sheet read as a white desk
                                ("cyl", (0, -0.98, 0.7), (0.07, 0.07, 0.5), (0, math.pi / 2, math.pi / 2))])])
        import bmesh                                            # rounded pad: a 2.5 cm bevel on the padded slab and the head section only (user: round the bed pads); dimensions unchanged
        k_pad = next((k for k, m in enumerate(o.data.materials) if m is pad), None)
        if k_pad is not None:
            bm = bmesh.new(); bm.from_mesh(o.data)
            edges = [e for e in bm.edges if any(f.material_index == k_pad for f in e.link_faces)]
            bmesh.ops.bevel(bm, geom=edges, offset=0.025, offset_type="OFFSET", segments=2, affect="EDGES")
            bm.to_mesh(o.data); bm.free()
        return o


class PrivacyCurtainFactory:
    """Ceiling-hung privacy curtain (front +X): an L-shaped track at 2.3 m with a pleated fabric panel down to 0.3 m off the floor."""
    def __init__(self, seed, L=2.6, D=1.6):                       # longer than a 2.27 m couch: a 2.2 m run's return crossed its head end
        r = random.Random(seed)
        self.L, self.D = L, D; self.c = r.choice(((0.55, 0.7, 0.72), (0.7, 0.75, 0.82), (0.82, 0.82, 0.8)))
        if STYLE.get("curtain_rgb"):                                  # the reference's curtain colour (exam room S18: blue)
            self.c = tuple(STYLE["curtain_rgb"])

    def spawn_asset(self, i):
        L, D = self.L, self.D
        fab = _flat(f"ir_curtain_{int(self.c[1] * 100)}", self.c, 0.9); rail = _flat("ir_desk_frame", (0.75, 0.75, 0.76), 0.35, 0.8)
        drawn = random.Random(i).uniform(0.22, 0.38)          # bunched back (clinic r3: a closed curtain hid the couch; r5: still hid the beds)
        # fabric folds: thin panels zig-zagging +-40 deg; parallel 5 cm slabs read as a folding screen (clinic r5 critic)
        n1, n2 = int(L * drawn / 0.06), int(D * 0.4 / 0.06)
        folds = [("box", (0.0, L / 2 - (k + 0.5) * 0.06, 1.32), (0.006, 0.075, 1.98), (0, 0, 0.7 if k % 2 else -0.7)) for k in range(n1)]
        folds += [("box", (-D / 2 + (k + 0.5) * 0.06, L / 2, 1.32), (0.075, 0.006, 1.98), (0, 0, 0.7 if k % 2 else -0.7)) for k in range(n2)]
        hooks = [("box", (0, L / 2 - (k + 0.5) * 0.06, 2.31), (0.012, 0.012, 0.03), (0, 0, 0)) for k in range(n1)]
        hooks += [("box", (0, y_, 2.33 + 0.35), (0.012, 0.012, 0.7), (0, 0, 0)) for y_ in (-L / 2 + 0.05, 0.0, L / 2 - 0.05)]   # ceiling hangers:
        hooks += [("box", (-D / 2 + 0.05, L / 2, 2.33 + 0.35), (0.012, 0.012, 0.7), (0, 0, 0))]   # a hung track, not a screen (clinic r17)
        return _prims(f"PrivacyCurtainFactory({i}).spawn_asset({i})",
                      [(fab, folds), (rail, hooks + [("box", (0, 0, 2.33), (0.03, L, 0.03), (0, 0, 0)),
                                                     ("box", (-D / 4, L / 2, 2.33), (D / 2, 0.03, 0.03), (0, 0, 0))])])


class DentalChairFactory:
    """Dental treatment unit (front +X = the patient's feet). The upholstery is one chained shape: a level seat, a backrest whose lower
    edge sits on the seat's back edge (reclined 32 deg), a headrest continuing it, a leg rest dropping from the seat's front edge -- each
    part positioned from its joint, so nothing floats (clinic r2: 'the chair comes apart'). A base column, armrests, an operating lamp on a
    post arching over the headrest, an instrument tray on a swing arm, a spittoon, and a dentist's stool."""
    def __init__(self, seed):
        r = random.Random(seed)
        # coloured upholstery only (dental r20: a white chair among white cabinets lost the room its function, 4/10 in 3 of 3 calls)
        self.c = r.choice(((0.05, 0.25, 0.5), (0.03, 0.35, 0.38), (0.15, 0.4, 0.25), (0.35, 0.1, 0.25)))
        self.side = r.choice((1, -1))

    def spawn_asset(self, i):
        sd, W = self.side, 0.56
        up = _flat(f"ir_dental_{int(self.c[1] * 100)}_{int(self.c[2] * 100)}", self.c, 0.35); white = _flat("ir_ac_white", (0.86, 0.86, 0.85), 0.4)
        steel = _flat("ir_chrome", (0.8, 0.8, 0.82), 0.15, 1.0); lamp = _flat("ir_led_panel", (1.0, 1.0, 1.0), 0.3)
        zs, x0, x1, t = 0.6, -0.25, 0.3, 0.13                    # seat: x from x0 (back edge) to x1 (front edge) at height zs
        a, Lb = math.radians(STYLE.get("dental_recline_deg", 32)), 0.68      # backrest: up from (x0, zs) at angle a (kit dental_recline_deg: S19 sits upright, 18)
        bx, bz = x0 - math.cos(a) * Lb / 2, zs + math.sin(a) * Lb / 2
        hx, hz = x0 - math.cos(a) * (Lb + 0.13), zs + math.sin(a) * (Lb + 0.13)     # headrest continues the backrest
        c, Ll = math.radians(28), 0.62                          # leg rest: down from (x1, zs) at angle c
        lx, lz = x1 + math.cos(c) * Ll / 2, zs - math.sin(c) * Ll / 2
        tip_x, tip_z = hx - math.cos(a) * 0.16, hz + math.sin(a) * 0.16
        return _prims(f"DentalChairFactory({i}).spawn_asset({i})",
                      [(up, [("rbox", ((x0 + x1) / 2, 0, zs), (x1 - x0, W, t), (0, 0, 0)),
                             ("rbox", (bx, 0, bz), (Lb, W, t), (0, a, 0)),
                             ("rbox", (hx, 0, hz), (0.26, 0.3, 0.1), (0, a, 0)),
                             ("rbox", (lx, 0, lz), (Ll, W - 0.06, t), (0, c, 0)),
                             ("rbox", (0.02, W / 2 + 0.05, zs + 0.17), (0.42, 0.08, 0.07), (0, 0, 0)),
                             ("rbox", (0.02, -W / 2 - 0.05, zs + 0.17), (0.42, 0.08, 0.07), (0, 0, 0)),
                             ("cyl", (0.65, -sd * 0.68, 0.52), (0.2, 0.2, 0.08), (0, 0, 0))]),          # stool seat
                       (white, [("box", (0, 0, 0.02), (0.75, 0.6, 0.04), (0, 0, 0)), ("rbox", (0.0, 0, 0.3), (0.34, 0.36, 0.56), (0, 0, 0)),
                                ("cyl", (0.0, sd * 0.5, 0.72), (0.035, 0.035, 0.2), (0, 0, 0)),
                                ("cyl", (0.0, sd * 0.5, 0.85), (0.09, 0.09, 0.07), (0, 0, 0))]),     # cuspidor: a small bowl on the chair
                                # side, not a white cone on a floor post ('a lampshade', floor E3 r15, 2 of 3)
                       (steel, [("cyl", (x0 - 0.05, -sd * 0.32, 1.15), (0.03, 0.03, 0.9), (0, 0, 0)),     # a short lamp post on the chair: the
                                ("sph", (x0 - 0.05, -sd * 0.32, 1.6), (0.055, 0.055, 0.055), (0, 0, 0)),     # E3 r28 GEO-01: 'sharp rectangular bars, no articulated joint housings': round arms, spherical joint housings and pivot caps
                                ("cyl", (x0 - 0.05, -sd * 0.16, 1.6), (0.022, 0.022, 0.3), (math.pi / 2, 0, 0)),
                                ("sph", (x0 - 0.05, 0.0, 1.6), (0.048, 0.048, 0.048), (0, 0, 0)),
                                ("cyl", ((x0 - 0.05 + tip_x + 0.15) / 2, 0, 1.6), (0.02, 0.02, abs(tip_x + 0.2 - x0)), (0, math.pi / 2, 0)),   # the 2.1 m one read as 'a floor-to-ceiling pole' (E3 r10, 3/3)
                                ("sph", (tip_x + 0.15, 0, 1.6), (0.05, 0.05, 0.05), (0, 0, 0)),
                                ("cyl", (tip_x + 0.15, 0, (1.6 + tip_z + 0.5) / 2), (0.016, 0.016, max(0.1, 1.6 - tip_z - 0.5)), (0, 0, 0)),
                                ("sph", (tip_x + 0.15, 0, tip_z + 0.5), (0.035, 0.035, 0.035), (0, 0, 0)),
                                ("sph", (tip_x + 0.15, 0, tip_z + 0.42), (0.17, 0.11, 0.05), (0, 0.5, 0)),     # lamp head: an oval shade with a handle
                                ("cyl", (tip_x + 0.27, 0, tip_z + 0.36), (0.012, 0.012, 0.12), (0, math.pi / 2 - 0.5, 0)),
                                ("cyl", (0.3, -sd * 0.75, 1.0), (0.02, 0.02, 0.5), (0, 0, 0)),             # monitor arm
                                ("cyl", (0.12, -sd * 0.6, 0.48), (0.025, 0.025, 0.96), (0, 0, 0)),
                                ("box", (0.12, -sd * 0.45, 0.98), (0.45, 0.32, 0.03), (0, 0, 0)),          # instrument tray
                                ("cyl", (0.65, -sd * 0.68, 0.24), (0.03, 0.03, 0.48), (0, 0, 0)),
                                ("box", (0.65, -sd * 0.68, 0.01), (0.45, 0.45, 0.02), (0, 0, 0.4))]),
                       (lamp, [("box", (tip_x + 0.15, 0, tip_z + 0.375), (0.24, 0.15, 0.005), (0, 0.5, 0))]),
                       # the patient monitor: a matte black body and a dark screen -- in chrome it mirrored the chair as 'a frosted
                       # panel with teal blobs floating beside it' (floor E3 r13, 3 of 3)
                       (_flat("ir_monitor_plastic", (0.03, 0.03, 0.035), 0.6), [("box", (0.3, -sd * 0.75, 1.32), (0.04, 0.42, 0.28), (0, 0, 0))]),
                       (_flat("ir_screen_dark", (0.01, 0.015, 0.02), 0.2), [("box", (0.3 + 0.021, -sd * 0.75, 1.32), (0.002, 0.38, 0.24), (0, 0, 0))])])


class WallBarsFactory:
    """Physio wall bars (front +X): two uprights, 10-14 round rungs, 0.9 m wide, 2.4 m tall; stands against a wall."""
    def __init__(self, seed):
        self.n = random.Random(seed).randint(10, 14)

    def spawn_asset(self, i):
        wood = _flat("ir_wallbars_wood", (0.72, 0.56, 0.36), 0.5)
        parts = [("box", (0, sy * 0.45, 1.2), (0.08, 0.05, 2.4), (0, 0, 0)) for sy in (1, -1)]
        parts += [("cyl", (0, 0, 0.2 + k * 2.1 / self.n), (0.017, 0.017, 0.9), (math.pi / 2, 0, 0)) for k in range(self.n)]
        return _prims(f"WallBarsFactory({i}).spawn_asset({i})", [(wood, parts)])


class ExerciseSetFactory:
    """Physio floor kit (front +X): a rolled-out mat, a gym ball, a couple of dumbbells on the mat."""
    def __init__(self, seed):
        r = random.Random(seed)
        self.mc = r.choice(((0.2, 0.45, 0.6), (0.3, 0.32, 0.35), (0.25, 0.55, 0.35)))   # clinical blues/greys/greens (clinic r16:
        self.bc = r.choice(((0.05, 0.2, 0.5), (0.1, 0.35, 0.15), (0.45, 0.3, 0.05)))       # 'pink/salmon poufs read as home decor';
        # grey read as a bin / pouf in r23 -- a saturated ball reads as a gym ball

    def spawn_asset(self, i):
        mat = _flat(f"ir_mat_{int(self.mc[0] * 100)}", self.mc, 0.8); ball = _flat(f"ir_gymball_{int(self.bc[0] * 100)}", self.bc, 0.35)
        black = _flat("ir_black_metal", (0.03, 0.03, 0.03), 0.4, 1.0)
        return _prims(f"ExerciseSetFactory({i}).spawn_asset({i})",
                      [(mat, [("box", (0, 0, 0.004), (0.6, 1.8, 0.008), (0, 0, 0))]),
                       (ball, [("sph", (0.05, 1.3, 0.32), (0.32, 0.32, 0.32), (0, 0, 0))]),   # a ball, not a drum (clinic r23, 3 of 3)
                       (black, [("cyl", (0.1, -0.5 + k * 0.25, 0.04), (0.04, 0.04, 0.3), (0, math.pi / 2, 0)) for k in range(2)])])


class ParallelBarsFactory:
    """Physio parallel walking bars (front +X): two 2.4-3.0 m steel handrails at 0.9 m on four posts, on a low platform."""
    def __init__(self, seed):
        self.L = random.Random(seed).choice((2.4, 3.0))

    def spawn_asset(self, i):
        L = self.L
        steel = _flat("ir_chrome", (0.8, 0.8, 0.82), 0.15, 1.0); base = _flat("ir_bars_platform_oak", (0.62, 0.46, 0.27), 0.5, wood=True)   # pale oak boards like the physio ref (S20: the dark rubber slab read as a grey mat)
        # (clinic r25: the blue platform read as 'an exercise mat laid under the bars', 2 of 3)
        posts = [("cyl", (sx * 0.3, sy * (L / 2 - 0.1), 0.47), (0.02, 0.02, 0.9), (0, 0, 0)) for sx in (1, -1) for sy in (1, -1)]
        rails = [("cyl", (sx * 0.3, 0, 0.92), (0.02, 0.02, L), (math.pi / 2, 0, 0)) for sx in (1, -1)]
        return _prims(f"ParallelBarsFactory({i}).spawn_asset({i})", [(steel, posts + rails), (base, [("box", (0, 0, 0.02), (0.9, L + 0.1, 0.04), (0, 0, 0))])])


class ExerciseBikeFactory:
    """Upright exercise bike (front +X): a frame, a flywheel housing, a saddle, handlebars and a console."""
    def __init__(self, seed):
        self.c = random.Random(seed).choice(((0.1, 0.1, 0.1), (0.85, 0.85, 0.85), (0.45, 0.47, 0.5)))      # no red frame: it clashed in the physio hall (S20 A/B)

    def spawn_asset(self, i):
        # stabiliser feet, a tube frame, a flywheel housing, saddle post, handlebar post with console, cranks; the old version stood a
        # 0.95 x 0.5 slab under tilted boxes and read as 'a tangle of black parts' (clinic r5 critic)
        body = _flat(f"ir_bike_{int(self.c[0] * 100)}", self.c, 0.4, 0.3); black = _flat("ir_black_metal", (0.03, 0.03, 0.03), 0.4, 1.0)
        tube = lambda p, q, r=0.025: ("cyl", tuple((a + b) / 2 for a, b in zip(p, q)), (r, r, math.dist(p, q)),
                                      (0, math.atan2(q[0] - p[0], q[2] - p[2]), 0))
        return _prims(f"ExerciseBikeFactory({i}).spawn_asset({i})",
                      [(body, [("cyl", (0.22, 0, 0.36), (0.26, 0.26, 0.1), (math.pi / 2, 0, 0)), tube((-0.4, 0, 0.06), (0.22, 0, 0.36), 0.035),
                               ("box", (0.36, 0, 1.06), (0.08, 0.26, 0.17), (0, -0.5, 0))]),
                       (black, [("box", (-0.42, 0, 0.03), (0.08, 0.5, 0.06), (0, 0, 0)), ("box", (0.42, 0, 0.03), (0.08, 0.5, 0.06), (0, 0, 0)),
                                tube((0.42, 0, 0.06), (0.22, 0, 0.36), 0.035), tube((-0.12, 0, 0.36), (-0.24, 0, 0.84)),
                                ("box", (-0.25, 0, 0.88), (0.26, 0.17, 0.06), (0, 0, 0)), tube((0.22, 0, 0.36), (0.33, 0, 1.0), 0.03),
                                ("cyl", (0.34, 0, 1.0), (0.016, 0.016, 0.48), (math.pi / 2, 0, 0)),
                                ("box", (0.05, 0.12, 0.28), (0.18, 0.02, 0.03), (0, 0.6, 0)), ("box", (0.05, -0.12, 0.28), (0.18, 0.02, 0.03), (0, -0.6, 0))])])


def _drape(objs, pin_fn=None, colliders=(), frames=36):
    """Let cloth meshes settle under gravity with Blender's cloth solver and bake the result into the mesh (user 2026-10-17: 'can the
    boutique's clothes hang and sag under gravity, fall on the floor'). `pin_fn(world_z, zmax)` pins vertices (the shoulders on a hanger);
    `colliders` are temporary objects the cloth rests on (a floor plane at the object's z=0). Each garment is thinned to ~30 % first: the
    Infinigen shirt has 17k faces and the solver needs a few thousand."""
    from mathutils import Matrix
    sc, vl = bpy.context.scene, bpy.context.view_layer
    f0 = sc.frame_current
    live = []
    for o in objs:
        if vl.objects.get(o.name) is None:
            for c in list(o.users_collection):
                c.objects.unlink(o)
            sc.collection.objects.link(o)
        o.data.transform(o.matrix_world); o.matrix_world = Matrix.Identity(4)
        bpy.ops.object.select_all(action="DESELECT"); vl.objects.active = o; o.select_set(True)
        md = o.modifiers.new("ir_thin", "DECIMATE"); md.ratio = 0.3
        bpy.ops.object.modifier_apply(modifier="ir_thin")
        if pin_fn is not None:
            zs = [v.co.z for v in o.data.vertices]; zmax = max(zs)
            vg = o.vertex_groups.new(name="ir_pin")
            vg.add([v.index for v in o.data.vertices if pin_fn(v.co.z, zmax)], 1.0, "REPLACE")
        cm = o.modifiers.new("ir_cloth", "CLOTH"); st = cm.settings
        st.quality = 6; st.mass = 0.25; st.tension_stiffness = st.compression_stiffness = st.shear_stiffness = 12.0; st.bending_stiffness = 0.6
        st.air_damping = 1.5
        if pin_fn is not None:
            st.vertex_group_mass = "ir_pin"
        cm.collision_settings.use_collision = True; cm.collision_settings.distance_min = 0.004; cm.collision_settings.use_self_collision = False
        cm.point_cache.frame_start = 1; cm.point_cache.frame_end = frames
        live.append(o)
    for c in colliders:
        if vl.objects.get(c.name) is None:
            sc.collection.objects.link(c)
        c.modifiers.new("ir_collide", "COLLISION")
    for f in range(1, frames + 1):
        sc.frame_set(f)
    for o in live:
        bpy.ops.object.select_all(action="DESELECT"); vl.objects.active = o; o.select_set(True)
        bpy.ops.object.modifier_apply(modifier="ir_cloth")
        if "ir_pin" in o.vertex_groups:
            o.vertex_groups.remove(o.vertex_groups["ir_pin"])
        for p in o.data.polygons:
            p.use_smooth = True
    for c in colliders:
        bpy.data.objects.remove(c, do_unlink=True)
    sc.frame_set(f0)



_CLOTH_OK = []


def _cloth(mod, name, seed, **attrs):
    """An Infinigen fabric mesh (clothes.shirt.ShirtFactory / towel.TowelFactory), or None when surface detail is off or the factory
    will not build: the boutique's garments were boxes ('boxes stacked like clothes', user 2026-10-17). One shirt is ~18k faces, a folded
    towel ~22k: a handful per rack or table, not dozens."""
    if not SURFACE_DETAIL or _CLOTH_OK == [False]:
        return None
    try:
        import importlib
        cls = getattr(importlib.import_module("infinigen.assets.objects.clothes." + mod), name)
        fac = cls(seed)
        for k, v in attrs.items():
            setattr(fac, k, v)
        o = fac.spawn_asset(seed)
        _CLOTH_OK[:] = [True]
        return o
    except Exception as e:                                       # noqa: BLE001  -- fall back to the box garments, never fail a scene
        print(f"[proc_assets] cloth {name} unavailable: {e!r}"[:200])
        _CLOTH_OK[:] = [False]
        return None


def _join_cloth(base, parts):
    """Bake `base`'s modifiers (the 3 mm bevel must not round the cloth) and join the cloth meshes into it, keeping every material slot."""
    vl = bpy.context.view_layer
    for o in [base] + parts:
        if vl.objects.get(o.name) is None:
            for c in list(o.users_collection):
                c.objects.unlink(o)
            bpy.context.scene.collection.objects.link(o)
    bpy.ops.object.select_all(action="DESELECT")
    vl.objects.active = base
    base.select_set(True)
    for md in list(base.modifiers):
        bpy.ops.object.modifier_apply(modifier=md.name)
    for o in parts:
        o.select_set(True)
    bpy.ops.object.join()
    return base


def _lib_load(f):
    """One finished Infinigen object from a data/plant_library .blend (origin at its base, +Z up), linked into the scene; None on failure."""
    try:
        with bpy.data.libraries.load(str(f), link=False) as (src, dst):
            dst.objects = list(src.objects)
        o = dst.objects[0]
        bpy.context.scene.collection.objects.link(o)
        return o
    except Exception as e:                                       # noqa: BLE001
        print(f"[proc_assets] plant library {Path(f).name}: {e!r}"[:200])
        return None


def _decimate(o, target):
    """Collapse-decimate a loaded library object to about `target` polygons (a monocot is 400k polys; a table plant must not cost that); no-op when already smaller."""
    n = len(o.data.polygons)
    if n <= target:
        return
    try:
        md = o.modifiers.new("ir_dec", "DECIMATE"); md.ratio = max(0.03, target / n)
        bpy.context.view_layer.objects.active = o
        bpy.ops.object.modifier_apply(modifier=md.name)
    except Exception as e:                                       # noqa: BLE001
        print(f"[proc_assets] decimate {o.name}: {e!r}"[:160])


def _infinigen_bunch(r, vase_parts, vase_h, n, h0, h1, spread, name):
    """A vase (the given parts) holding n Infinigen wild-flower stems (data/plant_library/flower_*.blend, grown offline by flower_gen.py) of height h0..h1 m; None when there is no library.
    Stems under 20k polys only; each is scaled to its own height, turned at random and tilted up to `spread` rad round the vase mouth."""
    import json
    if not SURFACE_DETAIL:
        return None
    try:
        idx = json.loads((PLANT_LIB / "flower_index.json").read_text())
    except Exception:                                            # noqa: BLE001
        return None
    stems = sorted(k for k, v in idx.items() if v["polys"] <= 20000)
    if not stems:
        return None
    base = _prims(name, vase_parts)
    parts = []
    for k in range(n):
        o = _lib_load(PLANT_LIB / r.choice(stems))
        if o is None:
            continue
        _decimate(o, 3500)
        hh = r.uniform(h0, h1); sc = hh / max(o.dimensions.z, 1e-3)
        o.scale = (sc, sc, sc)
        o.rotation_euler = (r.uniform(-spread, spread), r.uniform(-spread, spread), r.uniform(0, 6.28))
        o.location = (r.uniform(-0.025, 0.025), r.uniform(-0.025, 0.025), vase_h - 0.03)
        parts.append(o)
    if not parts:
        bpy.data.objects.remove(base, do_unlink=True)
        return None
    return _join_cloth(base, parts)


class TablePlantFactory:
    """A small potted plant for tables, desks and shelves (kit key infinigen_plants): a pot and one finished Infinigen monocot (data/plant_library/plant_*.blend) scaled to
    0.28-0.5 m (S10 r11: the ABO planter plants and procedural desk plants read as stiff)."""
    def __init__(self, seed):
        self.r = random.Random(seed); self.seed = seed
        self.pot = self.r.choice(((0.85, 0.83, 0.78), (0.6, 0.35, 0.22), (0.12, 0.12, 0.12), (0.7, 0.72, 0.68)))

    def spawn_asset(self, i):
        r = self.r
        if STYLE.get("floor_plant_style") in ("library_v2", "infinigen"):
            from room_planner import plant_lib2 as _pl2
            p_ = _pl2.plant("desk", self.seed, i, pot_rgb=self.pot) if _pl2.available() and SURFACE_DETAIL else None
            if p_ is not None:
                return p_
        files = sorted(f_ for f_ in PLANT_LIB.glob("plant_*.blend") if f_.stem[6:] not in (STYLE.get("plant_library_skip") or ())) if SURFACE_DETAIL else []     # kit plant_library_skip=["002", ...]: the spiky flower-stalk plants (O2 AST-01)
        o = _lib_load(files[(self.seed * 5 + i) % len(files)]) if files else None
        if o is None:
            return DeskPlantFactory(self.seed).spawn_asset(i)
        _decimate(o, 30000)
        h = r.uniform(0.28, 0.5)
        co = [v.co for v in o.data.vertices]
        top = max(c.z for c in co); wide = max(max(c.x for c in co) - min(c.x for c in co), max(c.y for c in co) - min(c.y for c in co))
        sc = min(h / max(top, 1e-3), 0.34 / max(wide, 1e-3))
        o.scale = (sc, sc, sc); o.location = (0, 0, 0.13)
        pot = _flat(f"ir_pot_{int(self.pot[0] * 100)}", self.pot, 0.8)
        base = _prims(f"TablePlantFactory({i}).spawn_asset({i})", [(pot, [("cyl", (0, 0, 0.07), (0.1, 0.13, 0.14), (0, 0, 0))])])
        return _join_cloth(base, [o])


class ClothingRackFactory:
    """Boutique clothing rail (front +X): a 1.2-1.6 m chrome rail at 1.5 m on two feet, 10-16 garments on hangers in a palette."""
    def __init__(self, seed):
        r = random.Random(seed)
        self.L = r.choice((1.2, 1.4, 1.6)); self.n = r.randint(10, 16); self.r = r
        self.pal = r.choice((((0.85, 0.82, 0.75), (0.2, 0.25, 0.35), (0.6, 0.45, 0.3)), ((0.1, 0.1, 0.1), (0.8, 0.8, 0.78), (0.55, 0.15, 0.15)),
                             ((0.7, 0.75, 0.65), (0.85, 0.75, 0.7), (0.35, 0.4, 0.3)),
                             # wider, warmer knitwear palettes (S15 ref: varied knits in camel / oatmeal / rust / sage / denim / burgundy)
                             ((0.78, 0.6, 0.38), (0.9, 0.86, 0.76), (0.62, 0.3, 0.18), (0.45, 0.52, 0.4), (0.3, 0.4, 0.55)),
                             ((0.55, 0.15, 0.2), (0.88, 0.8, 0.68), (0.2, 0.28, 0.4), (0.7, 0.55, 0.35), (0.5, 0.55, 0.45)),
                             ((0.93, 0.9, 0.84), (0.72, 0.62, 0.5), (0.35, 0.3, 0.26), (0.6, 0.7, 0.72), (0.8, 0.5, 0.4))))
        gs = STYLE.get("garment_sat")                           # kit garment_sat (< 1): mute the palette toward its grey (S15: 'garments too saturated')
        if gs is not None:
            self.pal = tuple(tuple((sum(c) / 3) + (x - sum(c) / 3) * gs for x in c) for c in self.pal)

    def spawn_asset(self, i):
        L, r = self.L, self.r
        chrome = _flat("ir_chrome", (0.8, 0.8, 0.82), 0.15, 1.0)
        groups = [(chrome, [(0, 0, 1.5, 0.03, L, 0.03), (0, L / 2 - 0.02, 0.75, 0.03, 0.03, 1.5), (0, -L / 2 + 0.02, 0.75, 0.03, 0.03, 1.5),
                            (0, L / 2 - 0.02, 0.01, 0.45, 0.04, 0.02), (0, -L / 2 + 0.02, 0.01, 0.45, 0.04, 0.02)])]
        hanger = _flat("ir_hanger_wood", (0.55, 0.4, 0.25), 0.5)
        n_c = min(self.n, 11)
        shirts = []
        if SURFACE_DETAIL and _CLOTH_OK != [False]:              # Infinigen shirts hung from the rail, turned ~35 deg so the fronts show
            yaw = r.uniform(0.5, 0.75) * r.choice((1, -1))
            for k in range(n_c):
                sh = _cloth("shirt", "ShirtFactory", r.randrange(10 ** 6))
                if sh is None:
                    shirts = []; break
                top = max(v.co.y for v in sh.data.vertices)
                y = -L / 2 + 0.08 + (k + 0.5) * (L - 0.16) / n_c
                sh.rotation_euler = (math.pi / 2, 0, yaw + r.uniform(-0.03, 0.03)); sh.location = (0.0, y, 1.43 - top)
                shirts.append(sh)
            if shirts and DRAPE:                                 # shoulders pinned to the hanger, the rest hangs; two fallen garments on the floor
                floor = bpy.data.objects.new("ir_drape_floor", bpy.data.meshes.new("ir_drape_floor"))
                bm_ = __import__("bmesh").new(); __import__("bmesh").ops.create_grid(bm_, x_segments=1, y_segments=1, size=2.5); bm_.to_mesh(floor.data); bm_.free()
                floor.location = (0, 0, 0.002)
                _drape(shirts, pin_fn=lambda z, zmax: z > zmax - 0.09, colliders=[floor])
                fallen = []
                for q in range(1 if r.random() < float(os.environ.get("ROOM_FALLEN_GARMENT_P", "0")) else 0):   # default 0: the crumpled cloth read as 'flat angular fragments at the foot of the rack' (S15 r27 AST-02); ROOM_FALLEN_GARMENT_P=0.4 restores the old 40 %
                   # one fallen garment under ~40 % of the racks: 18 racks x 1-2 read as scattered flat pads
                    fs = _cloth("shirt", "ShirtFactory", r.randrange(10 ** 6))
                    if fs is None:
                        break
                    fs.rotation_euler = (r.uniform(-0.6, 0.6), r.uniform(-0.6, 0.6), r.uniform(0, 6.28)); fs.location = (r.uniform(0.18, 0.4), r.uniform(-L * 0.3, L * 0.3), 0.3 + 0.12 * q)   # dropped tilted, it lands crumpled
                    fallen.append(fs)
                if fallen:
                    fl2 = bpy.data.objects.new("ir_drape_floor2", bpy.data.meshes.new("ir_drape_floor2"))
                    bm_ = __import__("bmesh").new(); __import__("bmesh").ops.create_grid(bm_, x_segments=1, y_segments=1, size=2.5); bm_.to_mesh(fl2.data); bm_.free()
                    fl2.location = (0, 0, 0.002)
                    _drape(fallen, pin_fn=None, colliders=[fl2], frames=30)
                    shirts += fallen
        if shirts:
            hang = [("box", (0, -L / 2 + 0.08 + (k + 0.5) * (L - 0.16) / n_c, 1.45), (0.4, 0.008, 0.02), (0.15, 0, 0)) for k in range(n_c)]
            rail = _prims(f"ClothingRackFactory({i}).spawn_asset({i})",
                          [(m, [("box", (cx, cy, cz), (sx, sy, sz), (0, 0, 0)) for cx, cy, cz, sx, sy, sz in parts]) for m, parts in groups]
                          + [(hanger, hang)])
            return _join_cloth(rail, shirts)
        hang, by_col = [], {}
        for k in range(self.n):                                  # a garment: hanger, shoulders, a body, two sleeves (shop r1: 'flat slabs')
            y = -L / 2 + 0.08 + (k + 0.5) * (L - 0.16) / self.n
            c = r.choice(self.pal); h = r.uniform(0.55, 1.05); w = r.uniform(0.38, 0.46); t = r.uniform(0.04, 0.08)
            hang.append(("box", (0, y, 1.45), (0.4, 0.008, 0.02), (0.15, 0, 0)))
            g = by_col.setdefault(c, [])
            # straight hems: ellipsoid bodies read as 'socks' (shop r5), flat boxes as 'slabs' (r4): a box body with a soft shoulder line;
            # the two end garments hang face-out, showing the silhouette (shoulders, sleeves) the side-on ones cannot
            face = k in (0, self.n - 1)
            if face:
                g.append(("box", (0, y, 1.41 - h / 2), (t, w * 0.85, h), (0, 0, 0)))
                g.append(("sph", (0, y, 1.39), (t * 0.6, w * 0.47, 0.05), (0, 0, 0)))
                for sy in (1, -1):
                    g.append(("cyl", (0, y + sy * w * 0.47, 1.17), (0.035, 0.045, 0.44), (sy * 0.15, 0, 0)))
            else:
                g.append(("sph", (0, y, 1.39), (w * 0.47, t * 0.55, 0.05), (0, 0, 0)))
                g.append(("box", (0, y, 1.41 - h / 2), (w * 0.85, t, h), (0, r.uniform(-0.03, 0.03), 0)))
                g.append(("box", (0, y, 1.41 - h + 0.04), (w * 0.92, t * 1.1, 0.08), (0, 0, 0)))          # hem
        groups.append((hanger, hang))
        for c, parts in by_col.items():
            groups.append((_flat(f"ir_garment_{int(c[0] * 100)}_{int(c[1] * 100)}", c, 0.9), parts))
        return _prims(f"ClothingRackFactory({i}).spawn_asset({i})", [(m, [("box", (cx, cy, cz), (sx, sy, sz), (0, 0, 0)) for cx, cy, cz, sx, sy, sz in parts])
                                                                     if parts and len(parts[0]) == 6 else (m, parts) for m, parts in groups])


class DisplayTableFactory:
    """Boutique display table (front +X): a 1.2-1.6 m wood or white table with stacks of folded clothes and a pair of shoes."""
    def __init__(self, seed):
        r = random.Random(seed)
        self.L = r.choice((1.2, 1.4, 1.6)); self.top = r.choice(((0.62, 0.5, 0.36), (0.9, 0.9, 0.88), (0.15, 0.15, 0.15))); self.r = r
        self.wood = False
        if STYLE.get("table_top") in COUNTER_TOPS:                # the kit's table top (S15: light oak; a 1-in-3 black top read as 'dark single-colour boxes')
            self.top = COUNTER_TOPS[STYLE["table_top"]][0]; self.wood = STYLE["table_top"] in WOODS

    def spawn_asset(self, i):
        L, r = self.L, self.r
        top = _flat(f"ir_disp_top_{int(self.top[0] * 100)}", self.top, 0.45, wood=self.wood); steel = _flat("ir_black_metal", (0.03, 0.03, 0.03), 0.4, 1.0)
        stacks = []
        folded = []
        if SURFACE_DETAIL and _CLOTH_OK != [False]:              # Infinigen folded cloth, 2-4 layers per pile, 3-4 piles
            for k in range(r.randint(3, 4)):
                x0, y0, z = r.uniform(-0.1, 0.1), -L / 2 + (k + 0.5) * L / 4.2, 0.76
                for j in range(r.randint(2, 4)):
                    t = _cloth("towel", "TowelFactory", r.randrange(10 ** 6), fold_type="fold")
                    if t is None:
                        break
                    co = [v.co for v in t.data.vertices]
                    mnx, mxx = min(c.x for c in co), max(c.x for c in co); mny, mxy = min(c.y for c in co), max(c.y for c in co)
                    sc = 0.32 / max(mxx - mnx, mxy - mny)
                    t.scale = (sc, sc, sc); t.rotation_euler = (0, 0, r.uniform(-0.12, 0.12))
                    t.location = (x0 - (mnx + mxx) / 2 * sc, y0 - (mny + mxy) / 2 * sc, z)
                    z += max(c.z for c in co) * sc
                    folded.append(t)
            if _CLOTH_OK == [False]:
                for t in folded:
                    bpy.data.objects.remove(t, do_unlink=True)
                folded = []
        for k in range(0 if folded else r.randint(3, 5)):        # folded garments: 2-6 layers, rounded fold edge, mixed shades
            x0, y0 = r.uniform(-0.15, 0.15), -L / 2 + (k + 0.5) * L / 5.2
            base = r.choice(_BRIGHT + ((0.85, 0.82, 0.75), (0.2, 0.25, 0.35)))
            for j in range(r.randint(2, 6)):
                c = tuple(min(1.0, max(0.0, v * r.uniform(0.8, 1.15))) for v in base)
                stacks.append((_flat(f"ir_folded_{int(c[0] * 100)}_{int(c[1] * 100)}_{int(c[2] * 100)}", c, 0.9),
                               [(x0 + r.uniform(-0.01, 0.01), y0 + r.uniform(-0.01, 0.01), 0.775 + j * 0.032, 0.3, 0.25, 0.028)]))
        tbl = _parts_object(f"DisplayTableFactory({i}).spawn_asset({i})",
                            [(top, [(0, 0, 0.74, 0.8, L, 0.04)]), (steel, [(0, sy * (L / 2 - 0.05), 0.36, 0.7, 0.04, 0.72) for sy in (1, -1)])] + stacks)
        return _join_cloth(tbl, folded) if folded else tbl


class MirrorFactory:
    """Free-standing full-length mirror (front +X), 0.6 x 1.8 m, black or brass frame, leaning slightly."""
    def __init__(self, seed):
        self.f = random.Random(seed).choice(((0.03, 0.03, 0.03), (0.7, 0.55, 0.3)))

    def spawn_asset(self, i):
        frame = _flat(f"ir_mirror_frame_{int(self.f[0] * 100)}", self.f, 0.3, 1.0); glass = _flat("ir_mirror", (0.95, 0.95, 0.95), 0.02, 1.0)
        return _prims(f"MirrorFactory({i}).spawn_asset({i})",
                      [(frame, [("box", (0, 0, 0.92), (0.04, 0.64, 1.84), (0, -0.08, 0))]), (glass, [("box", (0.021, 0, 0.92), (0.005, 0.56, 1.76), (0, -0.08, 0))])])


class FittingRoomFactory:
    """Fitting room cubicle (front +X): two side panels and a back panel 1.0 x 1.2 m, 2.2 m high, a curtain across the front, a hook."""
    def __init__(self, seed):
        r = random.Random(seed)
        self.c = tuple(STYLE["fitting_curtain_rgb"]) if STYLE.get("fitting_curtain_rgb") else r.choice(((0.85, 0.8, 0.72), (0.3, 0.3, 0.32), (0.55, 0.15, 0.15)))   # kit fitting_curtain_rgb: linen / taupe (S15 ref), not the random coral

    def spawn_asset(self, i):
        wall = _flat("ir_fitting_wall", (0.9, 0.9, 0.88), 0.5); fab = _flat(f"ir_curtain_{int(self.c[0] * 100)}", self.c, 0.85)
        rail = _flat("ir_black_metal", (0.03, 0.03, 0.03), 0.4, 1.0)
        # zig-zag fabric folds over 40-70% of the opening (shop r2: parallel slabs read as an unfinished partition)
        n = int(1.0 * random.Random(i).uniform(0.4, 0.7) / 0.06)
        folds = [("box", (0.6, 0.48 - (k + 0.5) * 0.06, 1.15), (0.006, 0.075, 1.95), (0, 0, 0.7 if k % 2 else -0.7)) for k in range(n)]
        return _prims(f"FittingRoomFactory({i}).spawn_asset({i})",
                      [(wall, [("box", (0, -0.52, 1.1), (1.2, 0.04, 2.2), (0, 0, 0)), ("box", (0, 0.52, 1.1), (1.2, 0.04, 2.2), (0, 0, 0)),
                               ("box", (-0.58, 0, 1.1), (0.04, 1.08, 2.2), (0, 0, 0))]),
                       (fab, folds), (rail, [("box", (0.6, 0, 2.15), (0.02, 1.0, 0.02), (0, 0, 0)),
                                             ("box", (-0.55, 0.3, 1.7), (0.06, 0.02, 0.02), (0, 0, 0))])])


class MenuBoardFactory:
    """Café menu board (front +X): a 1.2-1.8 m black chalkboard or light board in a wood/black frame with rows of chalk 'text' lines
    and price columns; hung on the wall above the bar (cafe r2: no café had one)."""
    def __init__(self, seed):
        r = random.Random(seed)
        self.W = r.choice((1.2, 1.5, 1.8)); self.dark = r.random() < 0.7; self.r = r

    def spawn_asset(self, i):
        W, H, r = self.W, 0.8, self.r
        if STYLE.get("menu_scale"):                              # kit: a bigger board (S6 r10: the menu text small on the back wall); the print's 1.875 aspect kept
            W = self.W * float(STYLE["menu_scale"]); H = W / 1.875
        pm = _pick_print("menu_pil_dark" if self.dark else "menu_pil_light", i) or _pick_print("menu_dark" if self.dark else "menu_light", i)          # crisp PIL-rendered menus first (S10/S6: the generated ones read 'KERY'); a printed menu: the flat slab with thin line boxes was
        board = _printed(pm, (0.04, 0.05, 0.05), 0.8) if pm is not None else \
            _flat("ir_chalkboard" if self.dark else "ir_menu_light", (0.04, 0.05, 0.05) if self.dark else (0.9, 0.88, 0.82), 0.8)   # 'flat' (user marks, S6-S9)
        frame = _flat("ir_menu_frame", (0.35, 0.24, 0.15) if self.dark else (0.05, 0.05, 0.05), 0.5)
        ink = _flat("ir_chalk" if self.dark else "ir_menu_ink", (0.85, 0.85, 0.8) if self.dark else (0.08, 0.08, 0.08), 0.9)
        lines = []
        for col in (-1, 1):
            for k in range(6):
                z = H - 0.14 - k * 0.1
                lines.append((0.012, col * W / 4 - 0.04, z, 0.002, W * r.uniform(0.18, 0.3), 0.022))
                lines.append((0.012, col * W / 4 + W / 6, z, 0.002, 0.07, 0.022))
        lines.append((0.012, 0, H - 0.06, 0.002, W * 0.35, 0.04))          # heading
        if pm is not None:
            lines = []                                                       # the print carries its own text
        return _parts_object(f"MenuBoardFactory({i}).spawn_asset({i})",
                             [(frame, [(0, 0, H / 2, 0.025, W + 0.06, H + 0.06)]), (board, [(0.008, 0, H / 2, 0.01, W, H)]), (ink, lines)])


class BanquetteFactory:
    """Fixed café banquette (front +X): an upholstered bench at 0.46 m with a tall back, 2.0-3.6 m long, on a plinth."""
    def __init__(self, seed, L=None):
        r = random.Random(seed)
        self.L = L or (r.uniform(*STYLE["banquette_len_m"]) if STYLE.get("banquette_len_m") else r.choice((2.0, 2.4, 3.0, 3.6)))      # kit banquette_len_m=[min,max]: one long run (H ref: a continuous leather banquette)
        self.c = r.choice(((0.45, 0.12, 0.1), (0.12, 0.3, 0.25), (0.55, 0.42, 0.25), (0.15, 0.15, 0.17), (0.7, 0.55, 0.2)))
        if STYLE.get("upholstery_rgb"):                          # the reference's leather / velvet (style eval chain G: random colour)
            self.c = tuple(STYLE["upholstery_rgb"])
        if STYLE.get("banquette_rgb"):                           # kit banquette_rgb: the banquette's own leather (H ref: BROWN leather, the chairs are mustard)
            self.c = tuple(STYLE["banquette_rgb"])

    def spawn_asset(self, i):
        L = self.L
        up = _flat(f"ir_banquette_{int(self.c[0] * 100)}_{int(self.c[1] * 100)}", self.c, 0.75); plinth = _flat("ir_black_metal", (0.03, 0.03, 0.03), 0.4, 1.0)
        n = max(2, int(L / 0.6))
        backs = [(-0.2, -L / 2 + (k + 0.5) * L / n, 0.75, 0.12, L / n - 0.02, 0.55) for k in range(n)]      # tufted back panels
        return _parts_object(f"BanquetteFactory({i}).spawn_asset({i})",
                             [(up, [(0.02, 0, 0.4, 0.5, L, 0.12)] + backs), (plinth, [(0, 0, 0.17, 0.5, L - 0.04, 0.34)])])


class CounterStoolFactory:
    """Commercial counter stool (front +X): a 0.62 m seat (round or square, polypropylene or upholstered) on a four-leg steel frame with
    a foot ring and a low back (pantry r8: ABO wooden saddle stools read as a farmhouse)."""
    def __init__(self, seed):
        r = random.Random(seed)
        if "stool" not in _ROOM_PICK:                            # one stool model per scene (pantry r16/r17: 'white high-backed stools
            _ROOM_PICK["stool"] = (r.choice(((0.1, 0.1, 0.1), (0.85, 0.85, 0.83), (0.2, 0.4, 0.55), (0.75, 0.45, 0.15), (0.55, 0.57, 0.58))),
                                   r.choice(((0.03, 0.03, 0.03), (0.75, 0.75, 0.76))))   # mixed with black backless ones at one table')
        self.c, self.frame = _ROOM_PICK["stool"]
        cs = STYLE.get("chair_style")                            # styled cafés: stools of the chair family (style eval: cream stools)
        if cs == "bentwood":
            self.c, self.frame = (0.035, 0.02, 0.012), (0.035, 0.02, 0.012)
        elif cs == "light_wood":
            self.c, self.frame = (0.62, 0.46, 0.3), (0.62, 0.46, 0.3)
        elif cs == "metal_bistro":
            self.c, self.frame = (0.04, 0.04, 0.045), (0.04, 0.04, 0.045)
        if STYLE.get("metal_finish") == "brass" and cs:
            self.frame = (0.55, 0.38, 0.12)

    def spawn_asset(self, i):
        seat = _flat(f"ir_stool_seat_{int(self.c[0] * 100)}_{int(self.c[2] * 100)}", self.c, 0.45)
        steel = _flat(f"ir_stool_frame_{int(self.frame[0] * 100)}", self.frame, 0.35, 1.0)
        legs = [("box", (sx * 0.15, sy * 0.15, 0.31), (0.025, 0.025, 0.62), (sy * 0.08, -sx * 0.08, 0)) for sx in (1, -1) for sy in (1, -1)]
        ring = [("box", (0, sy * 0.165, 0.25), (0.34, 0.02, 0.02), (0, 0, 0)) for sy in (1, -1)] + \
               [("box", (sx * 0.165, 0, 0.25), (0.02, 0.34, 0.02), (0, 0, 0)) for sx in (1, -1)]
        return _prims(f"CounterStoolFactory({i}).spawn_asset({i})",
                      [(steel, legs + ring), (seat, [("box", (0, 0, 0.635), (0.38, 0.38, 0.04), (0, 0, 0)), ("box", (-0.18, 0, 0.78), (0.03, 0.34, 0.2), (0, -0.15, 0))])])


class DrinkCansFactory:
    """Drink cans stacked on a counter (user 2026-10-16: 'cans of drinks piled up in the pantry'): a 2-layer block of 6-12 cans per
    layer in 1-3 brand colours, sometimes a cardboard tray under them."""
    def __init__(self, seed):
        r = random.Random(seed)
        self.nx, self.ny, self.layers = r.choice((2, 3)), r.choice((3, 4)), r.choice((1, 2, 2))
        self.cols = r.sample(_BRIGHT + ((0.75, 0.75, 0.78), (0.05, 0.05, 0.05)), r.randint(1, 3)); self.tray = r.random() < 0.5; self.r = r

    def spawn_asset(self, i):
        d, h, r = 0.067, 0.122, self.r
        rim = _flat("ir_chrome", (0.8, 0.8, 0.82), 0.15, 1.0)
        groups, by = [], {}
        for lz in range(self.layers):
            for ix in range(self.nx):
                for iy in range(self.ny):
                    if lz and r.random() < 0.25:
                        continue                                # an upper layer with gaps: some already taken
                    c = r.choice(self.cols)
                    by.setdefault(c, []).append(("cyl", ((ix - (self.nx - 1) / 2) * d, (iy - (self.ny - 1) / 2) * d, 0.01 + h / 2 + lz * h),
                                                 (d / 2, d / 2 - 0.002, h), (0, 0, 0)))
        for c, parts in by.items():
            groups.append((_flat(f"ir_can_{int(c[0] * 100)}_{int(c[1] * 100)}_{int(c[2] * 100)}", c, 0.25, 0.6), parts))
        if self.tray:
            groups.append((_flat("ir_cardboard_tray", (0.55, 0.42, 0.28), 0.8), [("box", (0, 0, 0.012), (self.nx * d + 0.01, self.ny * d + 0.01, 0.024), (0, 0, 0))]))
        groups.append((rim, [("cyl", (0, 0, 0.001), (0.001, 0.001, 0.001), (0, 0, 0))]))
        return _prims(f"DrinkCansFactory({i}).spawn_asset({i})", groups)


class SnackBasketFactory:
    """A wire / wicker basket of snack bags and bars on the pantry counter (user 2026-10-16: 'some snack bags')."""
    def __init__(self, seed):
        r = random.Random(seed)
        self.r = r; self.wire = r.random() < 0.5

    def spawn_asset(self, i):
        r = self.r
        basket = _flat("ir_black_metal", (0.03, 0.03, 0.03), 0.4, 1.0) if self.wire else _flat("ir_wicker", (0.6, 0.45, 0.28), 0.8)
        W, D, H = 0.36, 0.26, 0.12
        groups = [(basket, [("box", (0, 0, 0.005), (D, W, 0.01), (0, 0, 0)), ("box", (D / 2, 0, H / 2), (0.01, W, H), (0, 0, 0)),
                            ("box", (-D / 2, 0, H / 2), (0.01, W, H), (0, 0, 0)), ("box", (0, W / 2, H / 2), (D, 0.01, H), (0, 0, 0)),
                            ("box", (0, -W / 2, H / 2), (D, 0.01, H), (0, 0, 0))])]
        for k in range(r.randint(4, 7)):
            c = r.choice(_BRIGHT)
            groups.append((_flat(f"ir_snack_{int(c[0] * 100)}_{int(c[2] * 100)}", c, 0.3, 0.4),
                           [("box", (r.uniform(-0.07, 0.07), -W / 2 + 0.05 + k * (W - 0.1) / 6, 0.09 + r.uniform(0, 0.04)),
                             (0.04, 0.14, 0.2), (r.uniform(-0.5, 0.5), r.uniform(-0.3, 0.3), r.uniform(-0.3, 0.3)))]))
        return _prims(f"SnackBasketFactory({i}).spawn_asset({i})", groups)


class ProductBoxFactory:
    """A retail product (front +X): a cereal / cracker / tea / detergent box with a coloured body and a contrasting label band, or a
    bottle; sizes and colours vary per facing (shop r1: 'the same few primitives in a row')."""
    def __init__(self, seed):
        r = random.Random(seed); self.r = r
        self.kind = r.choice(("cereal", "cracker", "tea", "detergent", "bottle"))
        self.c1, self.c2 = r.sample(_BRIGHT + ((0.9, 0.85, 0.6), (0.2, 0.15, 0.1), (0.85, 0.85, 0.85)), 2)

    def spawn_asset(self, i):
        body = _flat(f"ir_prod_{int(self.c1[0] * 100)}_{int(self.c1[1] * 100)}_{int(self.c1[2] * 100)}", self.c1, 0.4)
        band = _flat(f"ir_prod_{int(self.c2[0] * 100)}_{int(self.c2[1] * 100)}_{int(self.c2[2] * 100)}", self.c2, 0.4)
        if self.kind == "bottle":
            h = self.r.uniform(0.2, 0.3)
            return _prims(f"ProductBoxFactory({i}).spawn_asset({i})", [(body, [("cyl", (0, 0, h * 0.4), (0.035, 0.035, h * 0.8), (0, 0, 0)),
                                                                              ("cyl", (0, 0, h * 0.9), (0.015, 0.012, h * 0.2), (0, 0, 0))]),
                                                                      (band, [("cyl", (0, 0, h * 0.45), (0.036, 0.036, h * 0.25), (0, 0, 0))])])
        d, w, h = {"cereal": (0.07, 0.19, 0.28), "cracker": (0.06, 0.2, 0.12), "tea": (0.07, 0.13, 0.08), "detergent": (0.12, 0.2, 0.25)}[self.kind]
        return _parts_object(f"ProductBoxFactory({i}).spawn_asset({i})", [(body, [(0, 0, h / 2, d, w, h)]),
                                                                          (band, [(d / 2 + 0.001, 0, h * 0.55, 0.002, w * 0.9, h * 0.3)])])


class PantryRunFactory:
    """Office pantry run (front +X): base cabinets + worktop, upper cabinets at 1.45-2.15 m, an inset sink under a tall gooseneck tap, an
    under-counter glass-door drinks fridge stocked with rows of cans, and a full-height stainless fridge column closing one end. The
    fridge is part of the run (pantry r9: a separate fridge stood in the middle of the floor; the 5 mm sink did not read)."""
    def __init__(self, seed, L=None):
        r = random.Random(seed)
        self.L = L or r.choice((2.4, 3.0, 3.6)); self.c = tuple(STYLE.get("pantry_rgb") or r.choice(((0.9, 0.9, 0.88), (0.35, 0.38, 0.4), (0.6, 0.48, 0.34))))   # kit pantry_rgb: the reference's cabinet colour (B r22: grey cabinets, want warm wood)
        self.r = r; self.fridge = True

    def spawn_asset(self, i):
        L, r = self.L, self.r
        Lc = L - 0.7 if self.fridge else L                       # cabinets; the last 0.7 m is the fridge column
        y0 = -L / 2                                             # cabinet run from y0 to y0 + Lc, fridge column after it
        cab = _flat(f"ir_pantry_cab_{int(self.c[0] * 100)}", self.c, 0.45); top = _flat("ir_counter_top_white_stone", (0.86, 0.85, 0.82), 0.25)
        steel = _flat("ir_steel", (0.62, 0.62, 0.64), 0.2, 1.0); gap = _flat("ir_black_metal", (0.03, 0.03, 0.03), 0.4, 1.0)
        glass = _flat("ir_fridge_glass", (0.85, 0.9, 0.92), 0.05, transmission=0.85)
        base = [(0, y0 + Lc / 2, 0.45, 0.6, Lc, 0.9)]
        doors = [(0.301, y0 + k * 0.6, 0.45, 0.002, 0.004, 0.8) for k in range(1, int(Lc / 0.6))]
        nu = max(1, int(Lc / 0.5))                               # upper doors: seams and pulls (clinic r14 / pantry r20: 'one blank,
        doors += [(0.041, y0 + k * Lc / nu, 1.8, 0.002, 0.004, 0.66) for k in range(1, nu)]          # doorless box')
        doors += [(0.048, y0 + (k + 0.5) * Lc / nu, 1.5, 0.012, 0.14, 0.012) for k in range(nu)]
        upper = [(-0.13, y0 + Lc / 2, 1.8, 0.34, Lc, 0.7)]
        sink_y = y0 + 0.75
        fz = y0 + Lc + 0.35                                      # fridge column centre
        bev_y = y0 + Lc - 0.35                                   # under-counter drinks fridge: last 0.6 m of the base run
        cans = []
        for row, zc in enumerate((0.18, 0.42, 0.66)):            # three shelves of cans seen through the glass door
            for k in range(7):
                cans.append((0.18, bev_y - 0.24 + k * 0.08, zc + 0.06, 0.066, 0.066, 0.12))
        can_cols = [(0.75, 0.12, 0.1), (0.1, 0.35, 0.7), (0.15, 0.55, 0.25), (0.95, 0.7, 0.1)]
        can_groups = []
        for j, c in enumerate(can_cols):
            part = cans[j::len(can_cols)]
            can_groups.append((_flat(f"ir_can_{int(c[0] * 100)}_{int(c[1] * 100)}_{int(c[2] * 100)}", c, 0.25, 0.6), part))
        strip = []
        if STYLE.get("pantry_strip"):                            # kit pantry_strip: a warm LED strip under the upper cabinets (B r22)
            led = _flat("ir_pantry_led", (1.0, 0.85, 0.6), 0.3); lb = led.node_tree.nodes["Principled BSDF"]; lb.inputs["Emission Color"].default_value = (1.0, 0.82, 0.55, 1); lb.inputs["Emission Strength"].default_value = 6.0
            strip = [(led, [(-0.02, y0 + Lc / 2, 1.442, 0.04, Lc - 0.1, 0.008)])]
        if not self.fridge:                                      # clinic cabinets: base + uppers + sink only
            return _parts_object(f"{type(self).__name__}({i}).spawn_asset({i})",
                                 [(cab, base + upper), (top, [(0.01, y0 + Lc / 2, 0.92, 0.62, Lc + 0.02, 0.04)]), (gap, doors),
                                  (steel, [(0.02, sink_y, 0.945, 0.44, 0.56, 0.012), (-0.22, sink_y, 1.17, 0.04, 0.04, 0.46),
                                           (-0.08, sink_y, 1.39, 0.3, 0.035, 0.035), (0.06, sink_y, 1.32, 0.035, 0.035, 0.14)]),
                                  (gap, [(0.02, sink_y, 0.95, 0.36, 0.48, 0.006)])] + strip)
        return _parts_object(f"PantryRunFactory({i}).spawn_asset({i})",
                             [(cab, base + upper), (top, [(0.01, y0 + Lc / 2, 0.92, 0.62, Lc + 0.02, 0.04)]), (gap, doors),
                              (steel, [(0.02, sink_y, 0.945, 0.44, 0.56, 0.012),                                 # sink rim
                                       (-0.22, sink_y, 1.17, 0.04, 0.04, 0.46),                                  # gooseneck: riser
                                       (-0.08, sink_y, 1.39, 0.3, 0.035, 0.035),                                 # arch over the bowl
                                       (0.06, sink_y, 1.32, 0.035, 0.035, 0.14),                                 # spout down
                                       (0.0, fz, 1.0, 0.66, 0.68, 2.0),                                          # fridge column
                                       (0.31, bev_y, 0.43, 0.02, 0.58, 0.84)]),                                  # drinks fridge frame
                              (gap, [(0.02, sink_y, 0.95, 0.36, 0.48, 0.006),                                    # dark basin
                                     (0.335, fz - 0.28, 1.15, 0.03, 0.03, 0.9), (0.331, fz, 1.32, 0.002, 0.66, 0.004),   # fridge handle, door split
                                     (0.335, fz - 0.28, 1.62, 0.03, 0.03, 0.42), (0.331, fz + 0.12, 1.12, 0.004, 0.22, 0.3),   # freezer handle,
                                     (0.331, fz - 0.333, 1.0, 0.004, 0.006, 2.0), (0.331, fz + 0.333, 1.0, 0.004, 0.006, 2.0),  # dispenser, gaskets

                                     (0.0, bev_y, 0.43, 0.5, 0.54, 0.8)]),                                       # dark fridge interior
                              (glass, [(0.322, bev_y, 0.43, 0.006, 0.54, 0.78)])] + can_groups + strip)


class ConferenceTableFactory:
    """Conference table (front +X): a 2.4-3.6 x 1.1-1.3 m top on two pedestal bases with a cable box in the middle. L/W fixed by the
    caller when the room decides (meeting_set sizes it so both long sides seat)."""
    def __init__(self, seed, L=None, W=None):
        r = random.Random(seed)
        self.L = L or r.choice((2.4, 3.0, 3.6)); self.W = W or r.uniform(1.1, 1.3)
        self.top = r.choice(((0.88, 0.87, 0.84), (0.45, 0.32, 0.2), (0.15, 0.15, 0.15)))
        if STYLE.get("desk_style") == "oak":
            self.top = (0.72, 0.55, 0.34)

    def spawn_asset(self, i):
        L, W, H = self.L, self.W, getattr(self, "H", 0.75)
        top = _flat(f"ir_conf_top_{int(self.top[0] * 100)}", self.top, 0.35, wood=STYLE.get("desk_style") == "oak"); base = _flat("ir_desk_frame", (0.75, 0.75, 0.76), 0.35, 0.8)
        black = _flat("ir_black_metal", (0.03, 0.03, 0.03), 0.4, 1.0)
        if os.environ.get("ROOM_SLIM_TABLE_LEGS") == "1" and type(self).__name__ == "BreakTableFactory":      # O2 r19 GEO-01: 'thick square slab legs with sharp junctions' -> four slim 5 cm legs set in from the corners, a thin apron and a low stretcher
            lg = [(sx * (W / 2 - 0.08), sy * (L / 2 - 0.12), (H - 0.05) / 2, 0.05, 0.05, H - 0.05) for sx in (1, -1) for sy in (1, -1)]
            lg += [(sx * (W / 2 - 0.08), 0, H - 0.09, 0.03, L - 0.3, 0.07) for sx in (1, -1)] + [(0, sy * (L / 2 - 0.12), 0.22, W - 0.2, 0.03, 0.03) for sy in (1, -1)]
            return _parts_object(f"{type(self).__name__}({i}).spawn_asset({i})", [(top, [(0, 0, H - 0.015, W, L, 0.035)]), (base, lg), (black, [(0, 0, H + 0.005, 0.22, 0.12, 0.012)])])
        return _parts_object(f"{type(self).__name__}({i}).spawn_asset({i})",
                             [(top, [(0, 0, H - 0.015, W, L, 0.035)]),
                              (base, [(0, sy * L * 0.28, (H - 0.03) / 2, W * 0.35, 0.12, H - 0.03) for sy in (1, -1)]),
                              (black, [(0, 0, H + 0.005, 0.22, 0.12, 0.012)])])


class BreakTableFactory(ConferenceTableFactory):
    """Office break-room table (user critique 2026-10-16: a wooden dining table reads as a home): laminate top on pedestal bases;
    a 1.05 m high table for bar stools."""
    def __init__(self, seed):
        r = random.Random(seed)
        self.L = r.choice((1.4, 1.6, 1.8)); self.W = 0.8; self.H = 0.92   # counter height: matches counter stools (r5: 1.06 table vs 0.94 stools)
        self.top = r.choice(((0.92, 0.92, 0.9), (0.15, 0.15, 0.15), (0.62, 0.5, 0.36)))
        if STYLE.get("table_top") in COUNTER_TOPS:               # a styled café's communal table shares the kit's top (style eval: white laminate)
            self.top = COUNTER_TOPS[STYLE["table_top"]][0]
        self.round_ = STYLE.get("break_table_shape") == "round"   # kit: ONE round oak pedestal table (B r16 refs: 'one round oak pedestal table, ours several rectangular')
        if self.round_:
            self.L = self.W = 1.15; self.H = 0.75; self.top = (0.72, 0.55, 0.34)
        elif self.DIMS:                                          # (length, width) from the layout (RoomRealizer._fill_layout): a communal table as long as its chair rows
            self.L, self.W = self.DIMS

    DIMS = None

    def spawn_asset(self, i):
        if not getattr(self, "round_", False):
            return super().spawn_asset(i)
        oak = _flat("ir_brk_oak", (0.72, 0.55, 0.34), 0.45, wood=True); metal = _flat("ir_black_metal", (0.03, 0.03, 0.03), 0.4, 1.0)
        import math as _m                                          # a FLUTED oak pedestal: 14 thin vertical ribs around a core, a wider foot ring (B r17 ref: 'one fluted-pedestal oak table')
        ribs = [("cyl", (0.12 * _m.cos(k * 2 * _m.pi / 14), 0.12 * _m.sin(k * 2 * _m.pi / 14), 0.37), (0.022, 0.022, 0.7), (0, 0, 0)) for k in range(14)]
        return _prims(f"BreakTableFactory({i}).spawn_asset({i})", [(oak, [("cyl", (0, 0, 0.735), (0.58, 0.58, 0.035), (0, 0, 0))] + ribs + [("cyl", (0, 0, 0.37), (0.1, 0.1, 0.7), (0, 0, 0)), ("cyl", (0, 0, 0.02), (0.22, 0.22, 0.04), (0, 0, 0))])])


class GlassPartitionFactory:
    """A full-height glass partition (front +X, length along local y): panes ~1.1 m between black steel mullions, base and head rails.
    door_at: offset along y of a 0.95 m glass door (or None). Origin at the bottom centre."""
    def __init__(self, seed, L=3.6, H=2.8, door_at=None):
        self.L, self.H, self.door_at = L, H, door_at

    def spawn_asset(self, i):
        L, H = self.L, self.H
        glass = _flat("ir_partition_glass", (0.95, 0.96, 0.96), 0.02, transmission=1.0); steel = _flat("ir_black_metal", (0.03, 0.03, 0.03), 0.4, 1.0)
        frames = [(0, 0, 0.025, 0.06, L, 0.05), (0, 0, H - 0.03, 0.06, L, 0.06)]
        n = max(1, round(L / 1.1))
        for k in range(n + 1):
            frames.append((0, -L / 2 + k * L / n, H / 2, 0.05, 0.04, H))
        panes = [(0, -L / 2 + (k + 0.5) * L / n, H / 2, 0.012, L / n - 0.05, H - 0.1) for k in range(n)]
        if self.door_at is not None:                              # a glass door leaf in its own frame
            y = self.door_at
            panes = [p for p in panes if abs(p[1] - y) > 0.6]
            frames += [(0, y - 0.48, 1.05, 0.05, 0.04, 2.1), (0, y + 0.48, 1.05, 0.05, 0.04, 2.1), (0, y, 2.12, 0.05, 1.0, 0.05),
                       (0.03, y + 0.3, 1.05, 0.03, 0.02, 0.5)]   # pull handle
            panes.append((0, y, 1.06, 0.012, 0.9, 2.04))
        return _parts_object(f"GlassPartitionFactory({i}).spawn_asset({i})", [(glass, panes), (steel, frames)])


class MedicalCabinetFactory(PantryRunFactory):
    """Clinic cabinet run (base + upper, sink): the pantry run in white laminate."""
    def __init__(self, seed, L=None):
        super().__init__(seed, L)
        self.c = (0.9, 0.9, 0.88); self.fridge = False


class ClinicDeskFactory(OfficeDeskFactory):
    """A small single-monitor clinic desk (clinic r1: the dual-monitor office desk was the hero of the exam and dental rooms)."""
    def __init__(self, seed):
        super().__init__(seed)
        self.L, self.D, self.dual = 1.2, 0.65, False


from room_planner.proc_boutique_flagship import StoneSlabTableFactory, WallRailFlatFactory, SteelLatticeScreenFactory   # noqa: E402,F401  (flagship boutique props)
