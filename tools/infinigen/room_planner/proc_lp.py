"""LP-record grid wall + raised herringbone platform (S34 high-ceiling LP cafe, user 2026-10-22).

    LpGridWallFactory   floor-to-ceiling black steel grid of 0.35 m cells, 14 x 14 (4.9 m wide, 4.9 m high, 0.34 m deep), each cell holding a sleeve face-out (one of the 12 invented covers in
                        data/venue_refs/floor_plans_v3/LPCAFE/sleeve_NN.png, random pick + a quarter-turn now and then), some cells empty, some with a stack of spines. Back at x = 0, front +X.
    RaisedPlatformFactory  an oak-herringbone platform 0.16 m high (4.0 x 2.4 m) with a black glass-balustrade frame on its open sides, front +X.
The covers are packed once into data/venue_refs/lp_cafe_highceiling_01/lp_atlas.png (4 x 3 cells of 256 px)."""
from __future__ import annotations

import math
import os
import random
from pathlib import Path

import bmesh
import bpy

from room_planner import proc_assets as pa
from room_planner import proc_boutique_flagship as fl

SRC = Path("/jarvis/project/robomituba/data/venue_refs/floor_plans_v3/LPCAFE")
ATLAS = Path("/jarvis/project/robomituba/data/venue_refs/lp_cafe_highceiling_01/lp_atlas48.png")
COLS, ROWS, CELL = 8, 6, 256                                  # 48 sleeve covers (sleeve_01..48.png = the 12 originals + Codex's 36 new ones; S34 CNT-02: the same motifs repeated)


def _atlas():
    if ATLAS.exists():
        return ATLAS
    from PIL import Image
    im = Image.new("RGB", (COLS * CELL, ROWS * CELL), (40, 40, 40))
    for k in range(COLS * ROWS):
        f = SRC / f"sleeve_{k + 1:02d}.png"
        if f.exists():
            im.paste(Image.open(f).convert("RGB").resize((CELL, CELL)), ((k % COLS) * CELL, (k // COLS) * CELL))
    ATLAS.parent.mkdir(parents=True, exist_ok=True)
    im.save(ATLAS)
    return ATLAS


PERMS = ((0, 1, 2),)          # 48 distinct covers now: no hue permutations (they were the stop-gap for 12 covers, S34 CNT-02)


def _sleeve_mat(variant=0):
    name = "ir_lp_sleeve" if variant == 0 else f"ir_lp_sleeve_v{variant}"
    m = bpy.data.materials.get(name)
    if m is not None:
        return m
    m = pa._flat(name, (0.5, 0.5, 0.5), 0.6)
    nt = m.node_tree; b = nt.nodes["Principled BSDF"]
    tx = nt.nodes.new("ShaderNodeTexImage"); tx.image = bpy.data.images.load(str(_atlas()), check_existing=True); tx.image.colorspace_settings.name = "sRGB"
    if variant == 0:
        nt.links.new(tx.outputs["Color"], b.inputs["Base Color"])
    else:
        sp = nt.nodes.new("ShaderNodeSeparateColor"); cb = nt.nodes.new("ShaderNodeCombineColor")
        nt.links.new(tx.outputs["Color"], sp.inputs["Color"])
        for q, src in enumerate(PERMS[variant]):
            nt.links.new(sp.outputs[("Red", "Green", "Blue")[src]], cb.inputs[("Red", "Green", "Blue")[q]])
        nt.links.new(cb.outputs["Color"], b.inputs["Base Color"])
    return m


def _box(bm, c, s, slot):
    r = bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=s, verts=r["verts"]); bmesh.ops.translate(bm, vec=c, verts=r["verts"])
    for f in {f for v in r["verts"] for f in v.link_faces}:
        f.material_index = slot


class LpGridWallFactory:
    NC, NR, CW, D = 14, 14, 0.35, 0.34

    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        r = self.r; NC, NR, CW, D = self.NC, self.NR, self.CW, self.D
        frame = fl._flat("ir_lp_frame", (0.025, 0.025, 0.03), 0.55); back = fl._flat("ir_lp_back", (0.05, 0.05, 0.055), 0.7)
        spine = [fl._flat(f"ir_lp_spine_{k}", c, 0.7) for k, c in enumerate(((0.8, 0.1, 0.08), (0.95, 0.75, 0.1), (0.1, 0.3, 0.65), (0.9, 0.9, 0.85), (0.1, 0.45, 0.25)))]
        sleeves = [_sleeve_mat(v_) for v_ in range(len(PERMS))]
        W, H = NC * CW, NR * CW
        bm = bmesh.new(); uv = bm.loops.layers.uv.verify()
        mats = [frame, back] + sleeves + spine
        S0 = 2 + len(sleeves)                                                               # first spine slot
        _box(bm, (0.01, 0, H / 2), (0.02, W, H), 1)                                         # back panel
        for k in range(NC + 1):                                                              # vertical dividers
            _box(bm, (D / 2, -W / 2 + k * CW, H / 2), (D, 0.02, H), 0)
        for k in range(NR + 1):                                                              # shelves
            _box(bm, (D / 2, 0, k * CW), (D, W, 0.02), 0)
        grid_ = {}
        for row in range(NR):
            for col in range(NC):
                y0 = -W / 2 + col * CW + 0.012; y1 = y0 + CW - 0.024; z0 = row * CW + 0.012; z1 = z0 + CW - 0.024
                t = r.random()
                if t < 0.03:
                    continue                                                                 # empty cell (3%: S34 r7 'long stretches of empty cubbies' at 12%)
                if t < 0.06:                                                                 # a few spines of records standing on the shelf
                    n = r.randint(5, 9); sw = (y1 - y0) / n
                    for s in range(n):
                        _box(bm, (D * 0.45, y0 + (s + 0.5) * sw, z0 + 0.15), (0.3, sw * 0.82, r.uniform(0.27, 0.3)), S0 + r.randrange(len(spine)))
                    continue
                near_ = {grid_.get((row + dr_, col + dc_)) for dr_ in range(-2, 3) for dc_ in range(-2, 3)}                # no cover repeated within 2 cells (S34 CNT-02)
                k = r.choice([q_ for q_ in range(COLS * ROWS) if q_ not in near_]); grid_[(row, col)] = k; u0, v0 = (k % COLS) / COLS, 1.0 - (k // COLS + 1) / ROWS
                q = [(y0, z0), (y1, z0), (y1, z1), (y0, z1)]
                us = [(u0, v0), (u0 + 1 / COLS, v0), (u0 + 1 / COLS, v0 + 1 / ROWS), (u0, v0 + 1 / ROWS)]
                rot = r.choice((0, 0, 0, 0, 0, 1, 2, 3)) if r.random() < 0.3 else 0           # now and then a quarter-turn
                us = us[rot:] + us[:rot]
                if r.random() < 0.35:
                    us = [us[1], us[0], us[3], us[2]]                                          # a mirrored cover
                vs = [bm.verts.new((D * 0.8, y, z)) for y, z in q]                        # the cover stands near the cubby mouth (S34 r15 CNT-04: at the back, 0.3 m deep in shadow, every sleeve rendered black and the cubbies read empty)
                f = bm.faces.new(vs); f.material_index = 2
                for lp, (uu, vv) in zip(f.loops, us):
                    lp[uv].uv = (uu, vv)
        me = bpy.data.meshes.new(f"LpGridWall({i})"); bm.to_mesh(me); bm.free()
        for m in mats:
            me.materials.append(m)
        o = bpy.data.objects.new(f"LpGridWallFactory({i}).spawn_asset({i})", me); bpy.context.scene.collection.objects.link(o)
        return o


class RaisedPlatformFactory:
    """Oak herringbone platform 4.0 x 2.4 x 0.16 m with a black balustrade frame (top rail 1.0 m, glass panes) on the front and one short side; front +X, origin at the back centre on the floor."""

    PL, PD = 4.0, 2.4                                      # length along the wall, depth into the room (layout size_m = [length, depth])

    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        oak = fl._flat("ir_rp_oak", (0.72, 0.5, 0.26), 0.5, wood=True); blk = fl._flat("ir_rp_black", (0.03, 0.03, 0.035), 0.5); gl = pa._flat("ir_rp_glass", (0.85, 0.9, 0.9), 0.05, 0.0, 0.9)
        L, D, H = self.PL, self.PD, 0.16
        deck = [("box", (D / 2, 0, H / 2), (D, L, H), (0, 0, 0))]
        rail = [("box", (D - 0.02, 0, 1.12), (0.04, L, 0.04), (0, 0, 0)), ("box", (D / 2, L / 2 - 0.02, 1.12), (D, 0.04, 0.04), (0, 0, 0))]
        posts = [("box", (D - 0.02, -L / 2 + 0.05 + k * (L - 0.1) / 4, H + 0.48), (0.04, 0.04, 0.96), (0, 0, 0)) for k in range(5)] + \
                [("box", (0.05 + k * (D - 0.1) / 3, L / 2 - 0.02, H + 0.48), (0.04, 0.04, 0.96), (0, 0, 0)) for k in range(4)]
        panes = [("box", (D - 0.02, -L / 2 + 0.05 + (k + 0.5) * (L - 0.1) / 4, H + 0.5), (0.01, (L - 0.1) / 4 - 0.05, 0.86), (0, 0, 0)) for k in range(4)] + \
                [("box", (0.05 + (k + 0.5) * (D - 0.1) / 3, L / 2 - 0.02, H + 0.5), ((D - 0.1) / 3 - 0.05, 0.01, 0.86), (0, 0, 0)) for k in range(3)]
        return pa._prims(f"RaisedPlatformFactory({i}).spawn_asset({i})", [(oak, deck), (blk, rail + posts), (gl, panes)])


class VehicleRampFactory:
    """A concrete vehicle ramp (S28F r2: 'the vehicle-ramp room is a flat unmarked floor'): 7.0 m long x 4.0 m wide, rising 1.4 m to the back (x = 0) and 0 at the front (x = 7), a solid wedge with white up-slope
    arrows along its centre line and yellow-black hazard stripes on both kerbs. Front +X (the low end), back at x = 0."""

    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        import math
        from mathutils import Euler
        L, W, H = 7.0, 4.0, 1.4
        ang = math.atan2(H, L)
        conc = fl._flat("ir_ramp_concrete", (0.42, 0.42, 0.4), 0.9); white = fl._flat("ir_ramp_white", (0.88, 0.88, 0.85), 0.8)
        yel = fl._flat("ir_ramp_yellow", (0.9, 0.7, 0.05), 0.7); blk = fl._flat("ir_ramp_black", (0.03, 0.03, 0.03), 0.8)
        bm = bmesh.new()
        a0 = [bm.verts.new((0, -W / 2, 0)), bm.verts.new((L, -W / 2, 0)), bm.verts.new((0, -W / 2, H))]          # the wedge: a triangle in xz, extruded across y
        b0 = [bm.verts.new((0, W / 2, 0)), bm.verts.new((L, W / 2, 0)), bm.verts.new((0, W / 2, H))]
        for f in (bm.faces.new(a0), bm.faces.new(b0[::-1]), bm.faces.new((a0[0], a0[1], b0[1], b0[0])), bm.faces.new((a0[1], a0[2], b0[2], b0[1])), bm.faces.new((a0[2], a0[0], b0[0], b0[2]))):
            f.material_index = 0
        bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))

        def tilted(cx, cy, along, w, t, slot, off=0.0):                                                         # a thin box lying on the slope at slope-distance `along` from the back (x), centred at y = cy
            s = along * math.cos(ang); z = H - along * math.sin(ang)
            r = bmesh.ops.create_cube(bm, size=1.0)
            bmesh.ops.scale(bm, vec=(cx, w, t), verts=r["verts"])                                                # cx here = length along the slope
            bmesh.ops.rotate(bm, cent=(0, 0, 0), matrix=Euler((0, ang, 0)).to_matrix(), verts=r["verts"])
            nz = (math.sin(ang), math.cos(ang))                                                                  # the slope's normal in xz
            bmesh.ops.translate(bm, vec=(s + nz[0] * (t / 2 + off), cy, z + nz[1] * (t / 2 + off)), verts=r["verts"])
            for f in {f for v in r["verts"] for f in v.link_faces}:
                f.material_index = slot
        for k in range(3):                                                                                        # three white up-slope arrows on the centre line
            d = 1.5 + k * 2.2
            tilted(1.0, 0, d + 0.1, 0.16, 0.012, 1)                                                              # shaft
            for hk_, hw_ in enumerate((0.62, 0.44, 0.26, 0.1)):                                                  # a stepped arrow head pointing up the slope (toward the back wall)
                tilted(0.12, 0, d - 0.5 - hk_ * 0.13, hw_, 0.012, 1)
        n = int((L / math.cos(ang)) / 0.5)
        for sy in (1, -1):                                                                                        # hazard stripes on both kerbs
            for k in range(n):
                tilted(0.5, sy * (W / 2 - 0.12), 0.25 + k * 0.5, 0.2, 0.014, 2 if k % 2 == 0 else 3)
        # S28F r4 LAY-02: the ramp ended against a solid wall. A dark vehicle opening above its top edge (3.2 x 1.7 m, black / yellow hazard border, a faint lit deck line at its head) reads as the doorway to the upper level
        void = fl._flat("ir_ramp_void", (0.008, 0.008, 0.01), 0.95); glow = fl._flat("ir_ramp_glow", (1.0, 0.7, 0.35), 0.5)
        gb_ = glow.node_tree.nodes["Principled BSDF"]; gb_.inputs["Emission Color"].default_value = (1.0, 0.7, 0.35, 1); gb_.inputs["Emission Strength"].default_value = 2.5
        PW, PH, PZ = 3.2, 1.7, H + 0.02

        def pbox(cx, cy, cz, sx, sy, sz, slot):
            r = bmesh.ops.create_cube(bm, size=1.0); bmesh.ops.scale(bm, vec=(sx, sy, sz), verts=r["verts"]); bmesh.ops.translate(bm, vec=(cx, cy, cz), verts=r["verts"])
            for f in {f for v in r["verts"] for f in v.link_faces}:
                f.material_index = slot
        pbox(0.03, 0, PZ + PH / 2, 0.06, PW, PH, 4)                                                              # the dark opening
        pbox(0.05, 0, PZ + PH - 0.04, 0.03, PW - 0.2, 0.05, 5)                                                   # the lit deck edge above it
        for k in range(int(PW / 0.2)):                                                                           # hazard border on the head and jambs
            pbox(0.07, -PW / 2 + 0.1 + k * 0.2, PZ + PH + 0.06, 0.03, 0.2, 0.12, 2 if k % 2 == 0 else 3)
        for sy in (1, -1):
            for k in range(int(PH / 0.2)):
                pbox(0.07, sy * (PW / 2 + 0.06), PZ + 0.1 + k * 0.2, 0.03, 0.12, 0.2, 2 if k % 2 == 0 else 3)
        me = bpy.data.meshes.new(f"VehicleRamp({i})"); bm.to_mesh(me); bm.free()
        for m in (conc, white, yel, blk, void, glow):
            me.materials.append(m)
        o = bpy.data.objects.new(f"VehicleRampFactory({i}).spawn_asset({i})", me); bpy.context.scene.collection.objects.link(o)
        return o


class RamenKitchenFactory:
    """The ramen shop's open kitchen block (S32 plan): 6.0 m long x 1.2 m deep x 2.6 m high, back wall at x = 0, front +X (towards the counter). A white square-tile back wall (2 cm dark grout lines every 10 cm),
    a steel extraction hood with a flue over a 3-burner range with stockpots, steel prep tables with an under-shelf, a steel sink, two wood open shelves with stacks of white bowls, and a walnut CANOPY BOX hanging
    2.0-2.45 m above the counter side (2.8 m long, 0.6 m deep) -- the reference's signature."""

    LEN = None

    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        r = self.r
        tile = fl._flat("ir_rk_tile", (0.92, 0.92, 0.9), 0.25); grout = fl._flat("ir_rk_grout", (0.45, 0.45, 0.45), 0.8); steel = fl._flat("ir_rk_steel", (0.66, 0.68, 0.7), 0.28, 1.0)
        dark = fl._flat("ir_rk_darksteel", (0.1, 0.1, 0.105), 0.4, 1.0); wal = fl._flat("ir_rk_walnut", (0.3, 0.16, 0.08), 0.45, wood=True); blk = fl._flat("ir_rk_black", (0.03, 0.03, 0.03), 0.5)
        bowl = fl._flat("ir_rk_bowl", (0.9, 0.9, 0.92), 0.25); wood = fl._flat("ir_rk_oak", (0.62, 0.38, 0.14), 0.45, wood=True); wh = fl._flat("ir_rk_board", (0.9, 0.9, 0.88), 0.5)
        L = self.LEN or float(pa.STYLE.get("ramen_kitchen_len_m") or 6.0)                    # layout size_m[0] / kit ramen_kitchen_len_m: the block's length
        LIBU = os.environ.get("ROOM_RAMEN_UTENSILS") == "1"                                       # kit-stage utensils (ramen_utensils.py) bring library pots / lids / spoons and procedural ladles: this factory then skips its own primitives
        R0 = (0, 0, 0)
        wall = [("box", (0.02, 0, 1.2), (0.04, L, 2.4), R0)]
        gr = [("box", (0.043, y, 1.2), (0.006, 0.01, 2.4), R0) for y in [-L / 2 + k * 0.1 for k in range(1, int(L / 0.1))]]
        gr += [("box", (0.043, 0, z), (0.006, L, 0.01), R0) for z in [k * 0.1 for k in range(2, 24)]]
        st, dk, bk = [], [], []                                                                 # brushed steel / dark steel / black
        y0 = -L / 2
        # --- the line, from the sink end: sink unit, work table, fridge, gas range, noodle boiler ---------------------------------------------------------------------------------
        ys, yt, yf, yr, yb = y0 + 0.55, y0 + 1.7, y0 + 2.85, y0 + 4.05, y0 + 5.05
        yb = min(yb, L / 2 - 0.45)
        def unit(yc, ln, h=0.9):                                                               # a steel base unit with a worktop lip
            st.extend([("box", (0.3, yc, h / 2 - 0.02), (0.56, ln, h - 0.06), R0), ("box", (0.31, yc, h - 0.02), (0.6, ln + 0.02, 0.04), R0)])
        unit(ys, 1.0); unit(yt, 1.3); unit(yf, 1.1); unit(yr, 1.3); unit(yb, 0.8)
        dk += [("box", (0.3, ys, 0.915), (0.42, 0.62, 0.03), R0)]                                # the sink basin (a darker inset) + a gooseneck tap
        st += [("cyl", (0.1, ys, 1.12), (0.015, 0.015, 0.4), R0), ("cyl", (0.17, ys, 1.31), (0.012, 0.012, 0.16), (0, 1.5708, 0))]
        st += [("box", (0.3, yt, 0.13), (0.5, 1.2, 0.03), R0)]                                  # the work table's under-shelf and its splash rail
        st += [("box", (0.06, yt, 1.0), (0.04, 1.3, 0.14), R0)]
        for q in (-1, 1):                                                                       # the fridge's two doors with long handles
            st += [("box", (0.585, yf + q * 0.27, 0.42), (0.02, 0.5, 0.74), R0)]; bk += [("box", (0.6, yf + q * 0.27 + q * -0.17 * -1, 0.48), (0.02, 0.02, 0.3), R0)]
        # gas range: a steel top with four black burner grates and a row of knobs, three stock pots of different sizes (lidded, steaming handles), one tall
        bk += [("box", (0.3 + dx, yr + dy, 0.945), (0.2, 0.2, 0.025), R0) for dx in (-0.1, 0.12) for dy in (-0.3, 0.3)] + [("cyl", (0.585, yr - 0.5 + k * 0.25, 0.7), (0.018, 0.018, 0.03), (0, 1.5708, 0)) for k in range(5)]
        pots = [(yr - 0.3, -0.1, 0.23, 0.46), (yr + 0.3, -0.1, 0.19, 0.58), (yr + 0.02, 0.12, 0.15, 0.3)]
        for py, px, rr, hh in ([] if LIBU else pots):
            st += [("cyl", (0.3 + px, py, 0.96 + hh / 2), (rr, rr, hh), R0), ("cyl", (0.3 + px, py, 0.96 + hh + 0.012), (rr * 1.04, rr * 1.04, 0.025), R0), ("cyl", (0.3 + px, py, 0.96 + hh + 0.045), (0.02, 0.02, 0.035), R0)]
            st += [("box", (0.3 + px, py + sg * (rr + 0.03), 0.96 + hh * 0.8), (0.05, 0.06, 0.02), R0) for sg in (1, -1)]
        # noodle boiler: a deep square steel unit on the work top with six basket wells, handles up, a rear steam pipe
        st += [("box", (0.3, yb, 1.12), (0.52, 0.66, 0.34), R0)]
        dk += [("cyl", (0.3 + dx, yb + dy, 1.292), (0.085, 0.085, 0.01), R0) for dx in (-0.12, 0.12) for dy in (-0.2, 0.0, 0.2)]
        bk += [("box", (0.3 + dx, yb + dy, 1.4), (0.012, 0.012, 0.2), (0, 0.35, 0)) for dx in (-0.12, 0.12) for dy in (-0.2, 0.0, 0.2)]
        st += [("cyl", (0.06, yb + 0.25, 1.4), (0.025, 0.025, 0.6), R0)]
        # utensil rail with ladles and strainers on the tile wall, above the work table and the range
        st += [("cyl", (0.07, (yt + yr) / 2, 1.72), (0.012, 0.012, yr - yt + 1.3), (1.5708, 0, 0))] if False else []
        rail_y0, rail_y1 = yt - 0.6, yr + 0.6
        st += [("box", (0.07, (rail_y0 + rail_y1) / 2, 1.6), (0.02, rail_y1 - rail_y0, 0.02), R0)]
        for k in range(0 if LIBU else 8):
            yy = rail_y0 + 0.15 + k * (rail_y1 - rail_y0 - 0.3) / 7
            st += [("box", (0.09, yy, 1.48), (0.012, 0.012, 0.28), R0), ("cyl", (0.09, yy, 1.32), (0.05 if k % 2 else 0.035, 0.05 if k % 2 else 0.035, 0.03), (1.5708, 0, 0))]
        # the hood: a big sloped brushed-steel exhaust canopy over the range and boiler (lip at 1.85 m, front face sloping back to a flue), filter strip, two flue boxes to the ceiling
        hy0, hy1 = yr - 0.85, min(yb + 0.55, L / 2 - 0.05); hc = (hy0 + hy1) / 2; hl = hy1 - hy0
        Hc = float(pa.STYLE.get("ramen_ceiling_m") or 2.5)                                      # kit ramen_ceiling_m: the room's ceiling height (S32: 2.56 m); the flue stops 4 cm under it
        st += [("box", (0.42, hc, 1.82), (0.78, hl, 0.06), R0),                                  # the lower lip / underside
               ("box", (0.78, hc, 2.0), (0.04, hl, 0.4), R0),                                    # the front face
               ("box", (0.4, hc, 2.2), (0.7, hl, 0.04), R0),                                     # the top
               ("box", (0.06, hc, 2.0), (0.04, hl, 0.4), R0),
               ("box", (0.4, hc, (2.2 + Hc - 0.04) / 2), (0.4, 0.45, Hc - 0.04 - 2.2), R0)]      # the flue up to the ceiling
        dk += [("box", (0.42, hc, 1.788), (0.5, hl - 0.2, 0.012), R0)]                            # the grease filters under the hood: a dark strip
        # a long low wooden soffit over the counter side (the reference's signature), honey oak, with a recessed light strip
        canopy = [("box", (0.95, 0.0, Hc - 0.24), (0.62, L - 0.1, 0.4), R0)]                     # a low honey-oak soffit running the length of the counter
        rods = []
        sh, bw = [], []
        for z in (1.45, 1.85):                                                                   # two wood open shelves on the tile wall, left half (over the sink and the table); FEW stacks of mixed sizes (S32 r14: 12 identical stacks in a row), some upside-down rice bowls and tea cups
            sh += [("box", (0.2, y0 + 1.7, z), (0.34, 2.2, 0.04), R0)]
            ypos = sorted(r.uniform(y0 + 0.75, y0 + 2.65) for _ in range(r.randint(3, 4)))
            for k, yc in enumerate(ypos):
                kind_ = r.choice(("big", "big", "rice", "rice", "dome"))
                if kind_ == "dome":                                                              # an upside-down rice bowl: a squashed dome on the shelf
                    bw += [("sph", (0.2 + r.uniform(-0.04, 0.04), yc, z + 0.045), (0.065, 0.065, 0.05), R0)]
                    continue
                rr_ = r.uniform(0.1, 0.125) if kind_ == "big" else r.uniform(0.06, 0.075)
                hh_ = 0.04 if kind_ == "big" else 0.032
                for h in range(r.randint(2, 5) if kind_ == "big" else r.randint(2, 4)):
                    bw += [("cyl", (0.2 + r.uniform(-0.006, 0.006), yc + r.uniform(-0.006, 0.006), z + 0.025 + hh_ / 2 + h * (hh_ + 0.005)), (rr_ - 0.004 * (h % 2), rr_ - 0.004 * (h % 2), hh_), R0)]
            for _ in range(r.randint(1, 2)):                                                     # a couple of tea cups
                bw += [("cyl", (0.2, r.uniform(y0 + 0.75, y0 + 2.65), z + 0.045), (0.035, 0.035, 0.06), R0)]
        # --- used-kitchen details by the sink (S32 r15 R6): a dish rack with plates, a water pitcher, a folded towel, order slips on a rail
        glass_ = pa._flat("ir_rk_glass", (0.85, 0.9, 0.9), 0.05, 0.0, 0.9); towel = fl._flat("ir_rk_towel", (0.92, 0.9, 0.84), 0.9); slip = fl._flat("ir_rk_slip", (0.93, 0.93, 0.9), 0.7); inkk = fl._flat("ir_rk_ink", (0.5, 0.06, 0.04), 0.7)
        wire, gl, tw, sl, ik = [], [], [], [], []
        rx, ry = 0.36, yt - 0.25                                                                  # dish rack on the work table: wire base + two side rails + 7 plates standing
        wire += [("box", (rx, ry, 0.945), (0.32, 0.34, 0.012), R0), ("box", (rx - 0.15, ry, 0.985), (0.012, 0.34, 0.08), R0), ("box", (rx + 0.15, ry, 0.985), (0.012, 0.34, 0.08), R0)]
        wire += [("box", (rx, ry - 0.17 + k * 0.057, 0.99), (0.3, 0.004, 0.07), R0) for k in range(7)]
        bw += [("cyl", (rx + r.uniform(-0.01, 0.01), ry - 0.15 + k * 0.05, 1.0), (0.12, 0.12, 0.012), (1.5708, 0, 0)) for k in range(6)]          # the plates: white ceramic discs standing on edge in the rack
        gl += [("cyl", (0.46, yt + 0.42, 1.04), (0.055, 0.055, 0.2), R0), ("box", (0.51, yt + 0.42, 1.06), (0.012, 0.02, 0.1), R0)]               # the water pitcher with a handle
        tw += [("box", (0.3, yt + 0.0, 0.955), (0.2, 0.14, 0.03), R0), ("box", (0.3, yt + 0.0, 0.985), (0.18, 0.13, 0.03), (0, 0, 0.1))]        # a folded towel, two layers
        st += [("box", (0.07, yt - 0.05, 1.18), (0.02, 0.6, 0.012), R0)]                          # an order-slip rail above the work table with 5 slips of different length
        for k in range(5):
            hh = r.uniform(0.08, 0.16); yy = yt - 0.25 + k * 0.1
            sl += [("box", (0.075, yy, 1.18 - hh / 2 - 0.005), (0.004, 0.06, hh), (0, 0, 0))]
            ik += [("box", (0.078, yy, 1.18 - hh / 2 + 0.01), (0.002, 0.04, 0.012), (0, 0, 0)), ("box", (0.078, yy, 1.18 - hh * 0.75), (0.002, 0.03, 0.01), (0, 0, 0))]
        return pa._prims(f"RamenKitchenFactory({i}).spawn_asset({i})", [(tile, wall), (grout, gr), (steel, st + wire), (dark, dk), (blk, bk + rods), (wood, canopy), (wal, sh), (bowl, bw), (glass_, gl), (towel, tw), (slip, sl), (inkk, ik)])


class RamenSeatSetFactory:
    """The condiment set at ONE ramen-counter stool (S32 r15 R3), real scale: a chopstick box (wood, 6 x 20 x 5 cm), a tissue box (white, 11 x 6 x 6 cm), a water cup (7 cm), two sauce bottles (soy, vinegar; 4.5 cm
    wide, 14-16 cm tall, red caps) and a pepper shaker, scattered loosely in a ~0.36 x 0.20 m patch with random yaw and offsets (no evenly spaced line); one seat in four also has a tray. Origin at the set's centre on the
    counter top, +X away from the cook (front of the counter)."""

    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        r = self.r
        steel = fl._flat("ir_rs_steel", (0.7, 0.72, 0.74), 0.25, 1.0); red = fl._flat("ir_rs_red", (0.65, 0.04, 0.03), 0.5); white = fl._flat("ir_rs_white", (0.93, 0.93, 0.9), 0.4)
        glass = pa._flat("ir_rs_glass", (0.85, 0.9, 0.9), 0.05, 0.0, 0.9); soy = fl._flat("ir_rs_soy", (0.03, 0.015, 0.01), 0.15); vin = fl._flat("ir_rs_vinegar", (0.35, 0.2, 0.06), 0.2)
        wood = fl._flat("ir_rs_pick", (0.55, 0.36, 0.18), 0.6)
        G = {k: [] for k in ("white", "steel", "red", "glass", "soy", "vin", "wood")}
        spots, tries = [], 0
        while len(spots) < 6 and tries < 60:                                                              # six items placed with a minimum spacing: a loose cluster, not a row
            tries += 1; y = r.uniform(-0.17, 0.17); x = r.uniform(-0.085, 0.085)
            if all((x - a) ** 2 + (y - b) ** 2 > 0.07 ** 2 for a, b in spots):
                spots.append((x, y))
        while len(spots) < 6:
            spots.append((r.uniform(-0.08, 0.08), r.uniform(-0.17, 0.17)))
        z0 = 0.012 if r.random() < 0.25 else 0.0
        items = ["sticks", "tissue", "cup", "soy", "vinegar", "pepper"]; r.shuffle(items)
        libs = []                                                                                           # ROOM_RAMEN_UTENSILS=1 and a library: soy / vinegar bottles and the water cup come from data/object_library_v2 (label-swapped), scaled to real condiment size
        LIBU = os.environ.get("ROOM_RAMEN_UTENSILS") == "1"
        if LIBU:
            try:
                from room_planner import lib_objects as _lo
                if not _lo._index():
                    LIBU = False
            except Exception:                                                                       # noqa: BLE001
                LIBU = False
        for (x, y), it in zip(spots, items):
            yaw = r.uniform(-0.6, 0.6) if it in ("sticks", "tissue") else 0.0
            if LIBU and it in ("cup", "soy", "vinegar"):
                libs.append((it, x, y, z0, yaw)); continue
            if it == "sticks":
                G["wood"] += [("box", (x, y, 0.025 + z0), (0.06, 0.2, 0.05), (0, 0, yaw))]; G["red"] += [("box", (x, y, 0.052 + z0), (0.04, 0.17, 0.004), (0, 0, yaw))]
            elif it == "tissue":
                G["white"] += [("box", (x, y, 0.03 + z0), (0.06, 0.11, 0.06), (0, 0, yaw))]; G["steel"] += [("box", (x, y, 0.062 + z0), (0.03, 0.07, 0.004), (0, 0, yaw))]
            elif it == "cup":
                G["glass"] += [("cyl", (x, y, 0.045 + z0), (0.035, 0.03, 0.09), (0, 0, 0))]
            elif it in ("soy", "vinegar"):
                m = "soy" if it == "soy" else "vin"; h = 0.15 if it == "soy" else 0.16; rr = 0.022
                G[m] += [("cyl", (x, y, h / 2 + z0), (rr, rr, h), (0, 0, 0))]; G["red"] += [("cyl", (x, y, h + 0.01 + z0), (rr * 0.8, rr * 0.8, 0.02), (0, 0, 0))]
            else:
                G["steel"] += [("cyl", (x, y, 0.035 + z0), (0.016, 0.016, 0.07), (0, 0, 0)), ("cyl", (x, y, 0.075 + z0), (0.018, 0.018, 0.01), (0, 0, 0))]
        if r.random() < 0.25:
            G["white"] += [("box", (0, 0, 0.006), (0.22, 0.38, 0.012), (0, 0, 0))]
        order = [("white", white), ("steel", steel), ("red", red), ("glass", glass), ("soy", soy), ("vin", vin), ("wood", wood)]
        base = pa._prims(f"RamenSeatSetFactory({i}).spawn_asset({i})", [(m, G[k]) for k, m in order])
        if libs:
            parts = []
            for it, x, y, z0_, yaw in libs:
                cat, sp, hgt = ("drinkware", "cup", 0.09) if it == "cup" else ("package", "bottle", 0.15 if it == "soy" else 0.16)
                pool = [m for m in _lo._index() if m["category"] == cat and m["species"] == sp]
                if not pool:
                    continue
                m = r.choice(pool); k_ = r.randrange(100) if cat == "package" and r.random() < 0.85 else None
                o = bpy.data.objects.new(f"RamenSeatLib_{sp}", _lo._mesh(m, k_)); bpy.context.scene.collection.objects.link(o)
                sc_ = hgt / max(m["size"][2], 1e-3); o.scale = (sc_, sc_, sc_); o.location = (x, y, z0_); o.rotation_euler = (0, 0, r.uniform(0, 6.28))
                parts.append(o)
            if parts:
                base = pa._join_cloth(base, parts)
        return base


class TicketMachineFactory:
    """A ramen-shop meal-ticket vending machine (S32 r15 R7): an upright cabinet 0.44 wide x 0.34 deep x 1.5 m, a lit menu panel with 12 small picture tiles on top, a grid of 3 x 6 push buttons (cream, red price chip each)
    in the middle, a coin slot, a note slot, a coin-return cup and a ticket outlet flap at the bottom, on a black base. Front +X, origin at the back-centre on the floor."""
    W, D, H = 0.44, 0.34, 1.5

    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        r = self.r; W, D, H = self.W, self.D, self.H
        from room_planner import proc_utensils as _pu
        body = _pu.plain("ir_tm_body", (0.78, 0.1, 0.08) if r.random() < 0.5 else (0.14, 0.14, 0.16), 0.35); panel = _pu.plain("ir_tm_panel", (0.92, 0.88, 0.76), 0.45); btn = _pu.plain("ir_tm_btn", (0.95, 0.93, 0.85), 0.25)
        chip = _pu.plain("ir_tm_chip", (0.7, 0.05, 0.04), 0.4); blk = _pu.plain("ir_tm_black", (0.03, 0.03, 0.035), 0.45); steel = _pu.plain("ir_tm_steel", (0.7, 0.72, 0.74), 0.25, 1.0)
        pic = [_pu.plain(f"ir_tm_pic{k}", c, 0.5) for k, c in enumerate(((0.75, 0.45, 0.15), (0.55, 0.3, 0.1), (0.85, 0.7, 0.3), (0.4, 0.5, 0.2)))]
        R0 = (0, 0, 0); xf = D                                                                            # the front face of the body (the body box is centred at D/2 with depth D): everything on the front sits at x = D + a few mm
        B = [("box", (D / 2, 0, 0.1 + (H - 0.1) / 2), (D, W, H - 0.1), R0)]
        K = [("box", (D / 2, 0, 0.05), (D + 0.02, W + 0.02, 0.1), R0), ("box", (xf + 0.004, 0, 1.28), (0.01, 0.32, 0.34), R0)]            # base + the recessed menu panel's dark surround
        P = [("box", (xf + 0.01, 0, 1.28), (0.008, 0.3, 0.32), R0)]
        PIC = [[], [], [], []]
        for q in range(12):
            gy, gz = q % 3, q // 3
            PIC[q % 4] += [("box", (xf + 0.016, (gy - 1) * 0.095, 1.40 - gz * 0.075), (0.006, 0.08, 0.06), R0)]
        BT, CH = [], []
        for row in range(6):
            for col in range(3):
                y = (col - 1) * 0.125; z = 1.03 - row * 0.065
                BT += [("box", (xf + 0.012, y, z), (0.014, 0.1, 0.04), R0)]; CH += [("box", (xf + 0.02, y, z - 0.016), (0.004, 0.05, 0.01), R0)]
        K += [("box", (xf + 0.006, 0.08, 0.57), (0.012, 0.05, 0.1), R0), ("box", (xf + 0.006, -0.08, 0.57), (0.012, 0.09, 0.02), R0), ("box", (xf + 0.01, 0, 0.45), (0.012, 0.16, 0.02), R0)]         # coin slot plate, note slot, change flap
        ST = [("box", (xf + 0.02, 0.0, 0.36), (0.045, 0.14, 0.05), R0), ("box", (xf + 0.012, 0.0, 0.25), (0.02, 0.22, 0.07), R0)]                                            # coin-return cup, ticket outlet flap
        return pa._prims(f"TicketMachineFactory({i}).spawn_asset({i})", [(body, B), (blk, K), (panel, P), (btn, BT), (chip, CH), (steel, ST)] + [(pic[k], PIC[k]) for k in range(4)])


class IslandCounterFactory:
    """A free-standing stadium-shaped (rounded-end) black coffee-counter island (S34 plan: the curved central counter): PL x PD m (default 4.2 x 1.6), 1.0 m high, dark stone top, the long sides faced with
    LP sleeves (two rows face-out, the invented covers from the LP atlas), a glass pastry case and two steel espresso machines with cups on top. Origin at the centre on the floor, long axis along y, front +X."""
    PL, PD = 4.2, 1.6

    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        r = self.r; L, D, H = self.PL, self.PD, 1.0
        body_m = fl._flat("ir_ic_body", (0.03, 0.03, 0.035), 0.45); top_m = fl._flat("ir_ic_top", (0.06, 0.06, 0.065), 0.3); steel = fl._flat("ir_ic_steel", (0.68, 0.7, 0.72), 0.28, 1.0)
        glass = pa._flat("ir_ic_glass", (0.9, 0.95, 0.95), 0.04, 0.0, 0.9); pastry = fl._flat("ir_ic_pastry", (0.8, 0.55, 0.25), 0.6); cup = fl._flat("ir_ic_cup", (0.93, 0.93, 0.9), 0.35)
        straight = L - D
        body = [("box", (0, 0, (H - 0.04) / 2), (D, straight, H - 0.04), (0, 0, 0))] + [("cyl", (0, sy * straight / 2, (H - 0.04) / 2), (D / 2, D / 2, H - 0.04), (0, 0, 0)) for sy in (1, -1)]
        top = [("box", (0, 0, H - 0.02), (D + 0.04, straight, 0.04), (0, 0, 0))] + [("cyl", (0, sy * straight / 2, H - 0.02), (D / 2 + 0.02, D / 2 + 0.02, 0.04), (0, 0, 0)) for sy in (1, -1)]
        case = [("box", (0.2, -0.9, H + 0.2), (0.5, 1.2, 0.4), (0, 0, 0))]
        pas = [("lsph", (0.2 + (k % 3 - 1) * 0.14, -0.9 + (k // 3 - 1.5) * 0.25, H + 0.1 + 0.06 * (k % 2)), (0.05, 0.05, 0.03), (0, 0, 0)) for k in range(12)]
        mach = [("box", (-0.15, sy * 1.2, H + 0.23), (0.45, 0.55, 0.46), (0, 0, 0)) for sy in (1,)] + [("box", (-0.15, 0.3, H + 0.23), (0.45, 0.55, 0.46), (0, 0, 0))]
        cups = [("cyl", (0.1 + 0.1 * (k % 2), 0.75 + 0.14 * (k // 2) + 0.0, H + 0.05), (0.035, 0.035, 0.1), (0, 0, 0)) for k in range(4)]
        o = pa._prims(f"IslandCounterFactory({i}).spawn_asset({i})", [(body_m, body), (top_m, top), (steel, mach), (glass, case), (pastry, pas), (cup, cups)])
        bm = bmesh.new(); bm.from_mesh(o.data); uv = bm.loops.layers.uv.verify()
        slot = len(o.data.materials); sleeve = _sleeve_mat()
        n = max(2, int((straight - 0.1) / 0.34))
        for sx in (1, -1):                                                           # LP sleeves face-out on both long sides, two rows
            for row, z0 in enumerate((0.22, 0.58)):
                for k in range(n):
                    y0 = -straight / 2 + 0.07 + k * (straight - 0.14) / n + 0.02; y1 = y0 + (straight - 0.14) / n - 0.04; z1 = z0 + 0.3
                    xs = sx * (D / 2 + 0.012)
                    q = [(xs, y0, z0), (xs, y1, z0), (xs, y1, z1), (xs, y0, z1)]
                    if sx < 0:
                        q = q[::-1]
                    c = r.randrange(COLS * ROWS); u0, v0 = (c % COLS) / COLS, 1.0 - (c // COLS + 1) / ROWS
                    us = [(u0, v0), (u0 + 1 / COLS, v0), (u0 + 1 / COLS, v0 + 1 / ROWS), (u0, v0 + 1 / ROWS)]
                    if sx < 0:
                        us = us[::-1]
                    f = bm.faces.new([bm.verts.new(v) for v in q]); f.material_index = slot
                    for lp, (uu, vv) in zip(f.loops, us):
                        lp[uv].uv = (uu, vv)
        bm.to_mesh(o.data); bm.free(); o.data.materials.append(sleeve)
        return o


class StandingLampFactory:
    """A classic standing floor lamp (S31 ref): a round brass-finished base disc, a slim brass pole 1.55 m, a pleated cream drum shade (0.4 m wide at the bottom, 0.3 m high, truncated cone) that glows warm
    from inside (emissive inner liner + the shade's own translucency); origin on the floor at the pole, 1.75 m tall, 0.4 m wide."""

    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        brass = fl._flat("ir_sl_brass", (0.78, 0.58, 0.25), 0.3, 1.0); shade = fl._flat("ir_sl_shade", (0.93, 0.88, 0.76), 0.85)
        glow = fl._flat("ir_sl_glow", (1.0, 0.85, 0.6), 0.4); gb = glow.node_tree.nodes["Principled BSDF"]
        gb.inputs["Emission Color"].default_value = (1.0, 0.8, 0.5, 1); gb.inputs["Emission Strength"].default_value = 2.5
        base = [("cyl", (0, 0, 0.015), (0.16, 0.16, 0.03), (0, 0, 0))]
        pole = [("cyl", (0, 0, 0.8), (0.012, 0.012, 1.54), (0, 0, 0))]
        cone = [("cyl", (0, 0, 1.6), (0.2, 0.15, 0.3), (0, 0, 0))]
        pleats = [("box", (0.2 * math.cos(a), 0.2 * math.sin(a), 1.6), (0.01, 0.025, 0.3), (0, 0, a)) for a in [k * 2 * math.pi / 28 for k in range(28)]]     # fine pleats round the shade
        liner = [("cyl", (0, 0, 1.6), (0.19, 0.14, 0.28), (0, 0, 0))]
        return pa._prims(f"StandingLampFactory({i}).spawn_asset({i})", [(brass, base + pole), (shade, cone + pleats), (glow, liner)])
