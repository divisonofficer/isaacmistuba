"""Props for the gourmet grocery market (reference set grocery_market_01_clean; docs/grocery_market_design_proposal.md). Factory-shaped (Cls(seed).spawn_asset(i), front +X).

  WireShelfFactory        chrome wire shelving (front +X): 4-5 wire-grid shelves on 4 posts, 1.25 / 1.875 / 2.5 m long, double-sided (0.9 m deep) or `single` (0.45 m); GondolaFactory-compatible
                          dims so the stock pass (which finds shelf boards by height) works; a coloured aisle-sign board hangs on two rods
  FoldingChairFactory     a folding metal chair (front +X): mint tube frame with crossed legs, a bamboo-toned seat and a back rail
  CeramicBirdShelfFactory a wall shelf unit (front +X, back at x = 0): 4 wood boards on black brackets carrying rows of egg-shaped glazed ceramic birds
"""
from __future__ import annotations

import math
import os
import random

from room_planner import proc_boutique_flagship as fl
from room_planner.proc_boutique_flagship import mesh_object

SIGNS = ((0.9, 0.75, 0.4), (0.92, 0.85, 0.6), (0.85, 0.7, 0.45))
GLAZE = ((0.08, 0.1, 0.14), (0.3, 0.38, 0.42), (0.55, 0.6, 0.55), (0.62, 0.3, 0.3), (0.9, 0.7, 0.2), (0.75, 0.78, 0.75), (0.12, 0.28, 0.2))


class WireShelfFactory:
    double = True

    def __init__(self, seed, single=False):
        r = random.Random(seed); self.r = r
        self.L = r.choice((1.25, 1.875, 2.5)); self.H = r.uniform(1.6, 1.9); self.double = not single and type(self).double
        self.sign = r.choice(SIGNS); self.levels = r.choice((4, 5))

    def spawn_asset(self, i):
        L, H, D = self.L, self.H, 0.9 if self.double else 0.45
        chrome = fl._flat("ir_wire_chrome", (0.75, 0.76, 0.78), 0.25, 1.0); sign = fl._flat(f"ir_wire_sign_{int(self.sign[0] * 100)}", self.sign, 0.55)
        posts = [("cyl", (sx * (D / 2 - 0.02), sy * (L / 2 - 0.02), 0.0), (sx * (D / 2 - 0.02), sy * (L / 2 - 0.02), H), 0.014, 8) for sx in (1, -1) for sy in (1, -1)]
        shelf, wires = [], []
        sides = (1, -1) if self.double else (1,)
        for sx in sides:
            xm = sx * D / 4 if self.double else 0.0; dep = D / 2 - 0.03 if self.double else D - 0.05
            for k in range(self.levels):
                z = 0.12 + k * (H - 0.25) / max(1, self.levels - 1)
                shelf.append(("box", xm, 0.0, z, dep, L - 0.04, 0.012))
                for j in range(int(dep / 0.06) + 1):                      # the wire grid: cross wires along y every 6 cm (front lip + back lip carry the look)
                    wires.append(("cyl", (xm - dep / 2 + j * 0.06, -L / 2 + 0.03, z + 0.008), (xm - dep / 2 + j * 0.06, L / 2 - 0.03, z + 0.008), 0.003, 4))
        parts = [(chrome, posts + [("box", 0.0, 0.0, 0.05, D - 0.04, L - 0.04, 0.03)] + [tuple(s) for s in shelf]), (chrome, wires)]
        board = [("box", sx * D * 0.25, 0.0, H + 0.45, 0.012, min(L - 0.1, 1.0), 0.28) for sx in sides] + [("cyl", (sx * D * 0.25, sy * (min(L - 0.1, 1.0) / 2 - 0.05), H), (sx * D * 0.25, sy * (min(L - 0.1, 1.0) / 2 - 0.05), H + 0.58), 0.004, 4) for sx in sides for sy in (1, -1)]
        parts.append((sign, board))
        return mesh_object(f"{type(self).__name__}({i}).spawn_asset({i})", parts, bevel=False)


class WireWallShelfFactory(WireShelfFactory):
    double = False


class FoldingChairFactory:
    def __init__(self, seed):
        r = random.Random(seed)
        self.c = r.choice(((0.45, 0.72, 0.58), (0.5, 0.75, 0.62), (0.4, 0.68, 0.55)))

    def spawn_asset(self, i):
        mint = fl._flat("ir_folding_mint", self.c, 0.45, 0.6); wood = fl._flat("ir_folding_seat", (0.78, 0.6, 0.3), 0.5, wood=True)
        r_ = 0.012; fr, bk = [], []
        for sy in (1, -1):                                                # side frames: a crossed leg pair + front rail
            fr.append(("cyl", (-0.2, sy * 0.2, 0.0), (0.2, sy * 0.2, 0.45), r_, 8)); fr.append(("cyl", (0.2, sy * 0.2, 0.0), (-0.2, sy * 0.2, 0.45), r_, 8))
            bk.append(("cyl", (-0.2, sy * 0.2, 0.45), (-0.22, sy * 0.2, 0.9), r_, 8))
        fr.append(("cyl", (0.2, -0.2, 0.45), (0.2, 0.2, 0.45), r_, 8)); bk.append(("cyl", (-0.22, -0.2, 0.9), (-0.22, 0.2, 0.9), r_, 8)); bk.append(("cyl", (-0.22, -0.2, 0.7), (-0.22, 0.2, 0.7), r_, 8))
        return mesh_object(f"FoldingChairFactory({self.c[0]:.2f}).spawn_asset({i})", [(mint, fr + bk), (wood, [("box", 0.0, 0.0, 0.46, 0.4, 0.42, 0.025), ("box", -0.21, 0.0, 0.78, 0.02, 0.4, 0.16)])], bevel=False)


class CeramicBirdShelfFactory:
    def __init__(self, seed):
        self.r = random.Random(seed); self.L = self.r.choice((1.6, 2.0))

    def spawn_asset(self, i):
        r, L = self.r, self.L
        wood = fl._flat("ir_cb_shelf_wood", (0.62, 0.45, 0.25), 0.55, wood=True); blk = fl._flat("ir_black_metal", (0.03, 0.03, 0.03), 0.4, 1.0)
        boards = [("box", 0.12, 0.0, 0.3 + k * 0.45, 0.24, L, 0.03) for k in range(4)]
        brackets = [("box", 0.06, sy * (L / 2 - 0.1 - m * L * 0.3), 0.3 + k * 0.45 - 0.08, 0.2, 0.02, 0.14) for k in range(4) for sy in (1, -1) for m in (0, 1)]
        groups = [(wood, boards), (blk, brackets)]; birds = {}
        for k in range(4):
            y = -L / 2 + 0.12
            while y < L / 2 - 0.1:
                c = r.choice(GLAZE); h = r.uniform(0.2, 0.28); w = h * 0.55
                birds.setdefault(c, []).extend([("sph", (0.12, y, 0.3 + k * 0.45 + 0.015 + h * 0.4), h * 0.42, 1), ("sph", (0.12, y, 0.3 + k * 0.45 + 0.015 + h * 0.85), h * 0.22, 1)])
                y += w + 0.06
        for c, p in birds.items():
            groups.append((fl._flat(f"ir_cb_glaze_{int(c[0] * 100)}_{int(c[1] * 100)}", c, 0.12), p))
        return mesh_object(f"CeramicBirdShelfFactory({i}).spawn_asset({i})", groups, bevel=False)


class BasketStackFactory:
    """Stacks of blue plastic shopping baskets on the floor (market ref: tall stacks by the entrance); a stack is 5-8 nested baskets, front +X."""
    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        n = self.r.randint(5, 8)
        blue = fl._flat("ir_basket_blue", (0.1, 0.28, 0.75), 0.45); grey = fl._flat("ir_basket_grey", (0.55, 0.57, 0.6), 0.5, 0.2)
        body, grip = [], []
        for k in range(n):
            z = 0.02 + k * 0.07; W, D = 0.42, 0.30
            body += [("box", 0, 0, z, D, W, 0.01), ("box", D / 2, 0, z + 0.12, 0.01, W + 0.05, 0.25), ("box", -D / 2, 0, z + 0.12, 0.01, W + 0.05, 0.25),
                     ("box", 0, W / 2 + 0.02, z + 0.12, D + 0.05, 0.01, 0.25), ("box", 0, -W / 2 - 0.02, z + 0.12, D + 0.05, 0.01, 0.25)]
        z = 0.02 + (n - 1) * 0.07
        grip += [("cyl", (0, -0.2, z + 0.26), (0, 0.2, z + 0.26), 0.012, 8)]
        return mesh_object(f"BasketStackFactory({i}).spawn_asset({i})", [(blue, body), (grey, grip)], bevel=False)


class BreadDisplayFactory:
    """A plywood bread table (front +X): a light plywood top on a plywood box base, 2 tiers, rows of round and long loaves in baskets."""
    def __init__(self, seed):
        self.r = random.Random(seed)

    def _bakery(self, i):
        """kit bread_display="bakery" (S35 refs): an oak island 1.6 x 0.8 x 0.45 m carrying three wood trays with stainless wire racks of wrapped buns, a tiered riser at the back with croissants and a rattan
        basket of baguettes, a second round basket of rolls, and small white price tags on clip stands; front +X."""
        import math
        r = self.r
        from room_planner import proc_assets as pa
        REAL = os.environ.get("ROOM_BREAD_REAL") == "1"                         # real bread shapes (proc_bread.py: scored baguettes / loaves, boules, split rolls, croissants) + baked-crust materials
        oak = fl._flat("ir_bk_oak", (0.62, 0.45, 0.26), 0.55, wood=True); steel = fl._flat("ir_bk_steel", (0.7, 0.72, 0.74), 0.3, 1.0); rattan = fl._flat("ir_bk_rattan", (0.40, 0.25, 0.11), 0.85)
        bun = fl._flat("ir_bk_bun", (0.78, 0.46, 0.17), 0.55); wrap = pa._flat("ir_bk_wrap", (0.95, 0.96, 0.95), 0.08, 0.0, 0.9); card = fl._flat("ir_bk_tag", (0.95, 0.95, 0.92), 0.5); crois = fl._flat("ir_bk_croissant", (0.78, 0.5, 0.18), 0.55)
        L, D = 1.6, 0.8
        if REAL:                                                                  # S35 strict review: oak panels (0.62, 0.45, 0.28) in a black 30 mm steel frame on a plinth, not a whitewashed box
            oak = pa._flat("ir_bk_oakpanel", (0.62, 0.45, 0.28), 0.45); frame_m = pa._flat("ir_bk_frame", (0.03, 0.03, 0.035), 0.4, 0.8)
            base = [("box", (0, 0, 0.255), (D - 0.06, L - 0.06, 0.4), (0, 0, 0)), ("box", (0, 0, 0.465), (D, L, 0.03), (0, 0, 0))]
            frame_parts = [("box", (sx * (D / 2 - 0.015), sy * (L / 2 - 0.015), 0.255), (0.03, 0.03, 0.4), (0, 0, 0)) for sx in (1, -1) for sy in (1, -1)] + [("box", (sx * (D / 2 - 0.015), 0, 0.06 + 0.03), (0.03, L, 0.03), (0, 0, 0)) for sx in (1, -1)] + [("box", (0, sy * (L / 2 - 0.015), 0.09), (D, 0.03, 0.03), (0, 0, 0)) for sy in (1, -1)] + [("box", (0, 0, 0.03), (D - 0.1, L - 0.1, 0.06), (0, 0, 0))]
        else:
            base = [("box", (0, 0, 0.225), (D, L, 0.45), (0, 0, 0))]
            frame_parts = []
        trays, rods, buns, wraps, tags = [], [], [], [], []
        tones = {"g": buns, "d": [], "p": [], "m": [], "x": []}            # golden / dark / pale / mid-brown / near-black crust tones (S35 r14 CNT-02)
        sz_ = lambda a: (a[0] * (k_ := r.uniform(0.8, 1.25)), a[1] * k_, a[2] * k_)
        for k in range(3):                                                       # three trays along the front half, each with a rack and 6-8 wrapped buns
            y = -L / 2 + 0.27 + k * 0.53; x = 0.17; z = 0.45
            trays += [("box", (x, y, z + 0.02), (0.42, 0.46, 0.04), (0, 0, 0))]
            trays += [("box", (x + sx * 0.21, y, z + 0.06), (0.02, 0.46, 0.06), (0, 0, 0)) for sx in (1, -1)] + [("box", (x, y + sy * 0.23, z + 0.06), (0.42, 0.02, 0.06), (0, 0, 0)) for sy in (1, -1)]
            rods += [("box", (x, y - 0.2 + j * 0.057, z + 0.075), (0.4, 0.004, 0.004), (0, 0, 0)) for j in range(8)] + [("box", (x - 0.18 + j * 0.12, y, z + 0.073), (0.004, 0.44, 0.004), (0, 0, 0)) for j in range(4)]
            kind_ = r.choice(("buns", "loaves", "baguettes", "pastry", "buns"))               # S35 CNT-02: each tray its own bakery item and crust tone, not 18 identical golden buns
            tg = r.choice(("g", "d", "p", "m", "x", "g", "m"))
            if r.random() < 0.14:
                kind_ = "soldout"                                                       # an empty tray: only its price tag left
            tt = lambda: tg if r.random() < 0.6 else r.choice(("g", "d", "p", "m"))   # a tray is mostly one bake, with a few of another
            if kind_ == "buns":
                for j in range(r.randint(10, 15)):
                    if r.random() < 0.15:
                        continue                                                        # a gap: sold out
                    bx, by = x + r.uniform(-0.12, 0.12), y + r.uniform(-0.17, 0.17)
                    tones[tt()].append((("bread:roll" if REAL else "lsph"), (bx, by, z + 0.075 + 0.03), sz_((0.055, 0.045, 0.032)), (0, 0, r.uniform(0, 3.14))))             # a squashed dome
                    if not REAL:
                        wraps.append(("lsph", (bx, by, z + 0.075 + 0.034), (0.064, 0.054, 0.042), (0, 0, 0)))                       # the thin clear cellophane over it
            elif kind_ == "loaves":                                                  # 3-4 oval loaves, slashed tops in a darker tone
                for j in range(r.randint(4, 5)):
                    by = y - 0.2 + j * 0.095 + r.uniform(-0.01, 0.01)
                    if r.random() < 0.2:
                        continue
                    tones[tt()].append((("bread:loaf" if REAL else "lsph"), (x + r.uniform(-0.03, 0.03), by, z + 0.075 + 0.04), sz_((0.17, 0.052, 0.045)), (0, 0, r.uniform(-0.15, 0.15))))
                    if r.random() < 0.35:                                                # a sliced loaf: the cut slices lie beside it
                        for q in range(3):
                            tones["p"].append(("lsph", (x + 0.17 + 0.03 * q, by + r.uniform(-0.03, 0.03), z + 0.075 + 0.02), (0.012, 0.045, 0.04), (0, 0, r.uniform(-0.3, 0.3))))
                    if not REAL:
                        tones["d"].append(("lsph", (x, by, z + 0.075 + 0.075), (0.1, 0.014, 0.012), (0, 0, 0)))                   # the slash (the real loaf has its scores in the mesh)
            elif kind_ == "baguettes":                                               # 4-5 long thin baguettes laid side by side
                for j in range(r.randint(4, 5)):
                    by = y - 0.17 + j * 0.085
                    if r.random() < 0.2:
                        continue
                    tones[tt()].append((("bread:baguette" if REAL else "lsph"), (x + r.uniform(-0.02, 0.02), by, z + 0.075 + 0.03), sz_((0.4, 0.034, 0.03)), (0, 0, r.uniform(-0.05, 0.05))))
            elif kind_ == "pastry":                                                  # small round pastries / rolls of mixed tones
                for j in range(r.randint(14, 20)):
                    bx, by = x + r.uniform(-0.14, 0.14), y + r.uniform(-0.18, 0.18)
                    if r.random() < 0.15:
                        continue
                    tones[r.choice(("g", "d", "p", "m", "x"))].append(((r.choice(("bread:roll", "bread:croissant")) if REAL else "lsph"), (bx, by, z + 0.075 + 0.022), sz_((0.055, 0.04, 0.03) if REAL else (0.04, 0.04, 0.025)), (0, 0, 0)))
            tags += [("box", (x + 0.24, y, z + 0.1), (0.004, 0.1, 0.06), (0, 0, 0))]
        riser = [("box", (-0.2, 0, 0.45 + 0.07), (0.28, L - 0.2, 0.14), (0, 0, 0)), ("box", (-0.28, 0, 0.45 + 0.14 + 0.07), (0.14, L - 0.3, 0.14), (0, 0, 0))]        # a stepped back riser
        pcs = []
        for j in range(5):                                                       # croissants on the first step
            if REAL:
                for jj in range(r.randint(2, 4)):
                    pcs.append(("bread:croissant", (-0.17, -0.58 + j * 0.2 + r.uniform(-0.03, 0.03), 0.45 + 0.14 + 0.03 + 0.02 * jj), (0.07, 0.045, 0.028), (0, 0, r.uniform(1.2, 2.0))))
                    break
                continue
            for q in range(5):                                                   # a croissant = a crescent of 5 tapering beads
                a_ = (q - 2) * 0.45; rr = 0.085
                pcs.append(("lsph", (-0.17 - (1 - math.cos(a_)) * 0.05, -0.55 + j * 0.2 + math.sin(a_) * rr, 0.45 + 0.14 + 0.03), (0.032 - abs(q - 2) * 0.006, 0.03 - abs(q - 2) * 0.005, 0.026), (0, 0, a_)))
        v_ = r.randrange(3)                                                      # three variants so the islands differ: (0) a small baguette basket on the riser, (1) two round roll baskets, (2) a low basket of loaves + a tray of croissants
        basket, loaves = [], []
        if v_ == 0:
            yb = r.uniform(-0.5, 0.5)
            basket += [("cyl", (-0.28, yb, 0.45 + 0.28 + 0.07), (0.11, 0.13, 0.14), (0, 0, 0))]
            loaves += [("cyl", (-0.28 + r.uniform(-0.03, 0.03), yb + r.uniform(-0.03, 0.03), 0.45 + 0.28 + 0.24), (0.028, 0.028, 0.34), (r.uniform(-0.1, 0.1), r.uniform(-0.1, 0.1), 0)) for _ in range(3)]
        elif v_ == 1:
            for yb in (-0.45, 0.4):
                basket += [("cyl", (-0.28, yb, 0.45 + 0.28 + 0.06), (0.14, 0.16, 0.12), (0, 0, 0))]
                loaves += [(r.choice(("bread:roll", "bread:boule")) if REAL else "lsph", (-0.28 + r.uniform(-0.07, 0.07), yb + r.uniform(-0.07, 0.07), 0.45 + 0.28 + 0.1 + r.uniform(0, 0.07)), sz_((0.06, 0.05, 0.04)), (r.uniform(-0.3, 0.3), 0, r.uniform(0, 3.14))) for _ in range(r.randint(9, 15))]
        else:
            basket += [("cyl", (0.0, r.uniform(-0.5, 0.5), 0.45 + 0.07), (0.16, 0.18, 0.12), (0, 0, 0))]
            loaves += [(r.choice(("bread:roll", "bread:boule", "bread:loaf")) if REAL else "lsph", (r.uniform(-0.05, 0.05), basket[0][1][1] + r.uniform(-0.06, 0.06), 0.45 + 0.14), (0.065, 0.05, 0.045), (0, 0, r.uniform(0, 3.14))) for _ in range(6)]
        if REAL:                                                                  # S35 strict + CNT-02: each island gets its own product mix, basket count, positions and heights
            mix = r.choice(("loaf", "pastry", "mixed")); n_b = {"loaf": 2, "pastry": 3, "mixed": 2}[mix]
            ys = sorted(r.sample([-0.55, -0.3, -0.05, 0.2, 0.45], n_b))
            for q, yb in enumerate(ys):
                kind = {"loaf": "loaf", "pastry": "croissant", "mixed": ("roll", "croissant")[q % 2]}[mix]; xb = r.uniform(0.1, 0.28); hb = r.uniform(0.09, 0.14)
                basket += [("cyl", (xb, yb, 0.45 + hb / 2 + 0.01), (r.uniform(0.14, 0.18), 0.12, hb), (0, 0, 0))]
                loaves += [(f"bread:{kind}", (xb + r.uniform(-0.05, 0.05), yb + r.uniform(-0.06, 0.06), 0.45 + hb + 0.02 * j), (0.07 if kind == "roll" else 0.11 if kind == "loaf" else 0.08, 0.055, 0.04), (0, 0, r.uniform(0, 3.14))) for j in range(r.randint(4, 8))]
            if mix != "pastry":                                                   # the upright baguette basket: height and place differ per island, absent on a pastry island
                hu = r.uniform(0.3, 0.46); yu = r.uniform(-0.3, 0.3); xu = r.uniform(-0.34, -0.2)
                basket += [("cyl", (xu, yu, 0.45 + 0.28 + hu / 2), (0.1, 0.11, hu), (0, 0, 0))]
                loaves += [("bread:baguette", (xu + r.uniform(-0.03, 0.03), yu + r.uniform(-0.04, 0.04), 0.45 + 0.28 + hu + 0.12), (0.2, 0.034, 0.03), (0, math.pi / 2 + r.uniform(-0.08, 0.08), r.uniform(0, 3.14))) for _ in range(r.randint(3, 5))]
            n_bag = {"loaf": 8, "pastry": 3, "mixed": 5}[mix]
            for j in range(n_bag):                                                # cellophane-bagged loaves along the front edge
                yy = -L / 2 + 0.15 + j * (L - 0.3) / max(1, n_bag - 1); xx = r.uniform(0.0, 0.1)
                loaves.append(("bread:loaf", (xx, yy, 0.45 + 0.04), (0.09, 0.05, 0.04), (0, 0, r.uniform(-0.2, 0.2)))); wraps.append(("box", (xx, yy, 0.45 + 0.045), (0.2, 0.11, 0.09), (0, 0, 0)))
        if REAL:
            from room_planner import proc_bread as _pb
            bun = _pb.crust_material("ir_bk_crust_g", (0.70, 0.42, 0.16), flour=0.2)
            dk_, pl_, md_, bk_ = (_pb.crust_material("ir_bk_crust_d", (0.45, 0.22, 0.08)), _pb.crust_material("ir_bk_crust_p", (0.70, 0.45, 0.20), flour=0.5), _pb.crust_material("ir_bk_crust_m", (0.58, 0.32, 0.12), flour=0.2), _pb.crust_material("ir_bk_crust_x", (0.22, 0.10, 0.045)))
        else:
            dk_, pl_, md_, bk_ = (fl._flat("ir_bk_bun_dark", (0.36, 0.19, 0.08), 0.6), fl._flat("ir_bk_bun_pale", (0.86, 0.68, 0.42), 0.65), fl._flat("ir_bk_bun_mid", (0.58, 0.32, 0.12), 0.6), fl._flat("ir_bk_bun_black", (0.2, 0.09, 0.04), 0.65))
        return pa._prims(f"BreadDisplayFactory({i}).spawn_asset({i})", [(oak, base + trays + riser), (steel, rods), (frame_m if REAL else steel, frame_parts), (bun, buns + pcs + loaves), (wrap, wraps), (rattan, basket), (card, tags),
                                                                                             (dk_, tones["d"]), (pl_, tones["p"]), (md_, tones["m"]), (bk_, tones["x"])])

    def spawn_asset(self, i):
        from room_planner import proc_assets as _pa
        if _pa.STYLE.get("bread_display") == "bakery":
            return self._bakery(i)
        r = self.r
        ply = fl._flat("ir_bread_ply", (0.72, 0.58, 0.38), 0.6, wood=True); crust = fl._flat("ir_bread_crust", (0.62, 0.38, 0.16), 0.7)
        pale = fl._flat("ir_bread_pale", (0.8, 0.62, 0.35), 0.7)
        L, D = 1.6, 0.8
        parts = [("box", 0, 0, 0.34, D, L, 0.04), ("box", 0, 0, 0.17, D - 0.1, L - 0.1, 0.34), ("box", -0.18, 0, 0.72, 0.4, L - 0.2, 0.03),
                 ("box", -0.18, 0, 0.53, 0.38, L - 0.24, 0.38)]
        loaves = []
        for tier, (x0, z0, dep) in enumerate(((0.12, 0.36, 0.5), (-0.18, 0.74, 0.3))):
            y = -L / 2 + 0.15
            while y < L / 2 - 0.12:
                if r.random() < 0.5:
                    loaves.append(("sph", (x0, y, z0 + 0.06), 0.09, 1)); y += 0.24
                else:
                    loaves.append(("cyl", (x0 - dep / 2 * 0.6, y, z0 + 0.05), (x0 + dep / 2 * 0.6, y, z0 + 0.05), 0.05, 8)); y += 0.15
        return mesh_object(f"BreadDisplayFactory({i}).spawn_asset({i})", [(ply, parts), (crust, loaves[::2]), (pale, loaves[1::2])], bevel=False)


class CrateStackFactory:
    """Stacked plastic produce crates (blue / grey / red) with a few vegetables on top, floor item, front +X."""
    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        r = self.r; col = r.choice(((0.1, 0.3, 0.7), (0.5, 0.52, 0.55), (0.75, 0.2, 0.15)))
        pl = fl._flat(f"ir_crate_{int(col[0] * 100)}_{int(col[2] * 100)}", col, 0.5); veg = fl._flat("ir_crate_veg", (0.35, 0.55, 0.2), 0.6)
        n = r.randint(2, 4); W, D, H = 0.6, 0.4, 0.25; body = []
        for k in range(n):
            z = k * H
            body += [("box", 0, 0, z + 0.01, D, W, 0.02), ("box", D / 2, 0, z + H / 2, 0.02, W, H), ("box", -D / 2, 0, z + H / 2, 0.02, W, H),
                     ("box", 0, W / 2, z + H / 2, D, 0.02, H), ("box", 0, -W / 2, z + H / 2, D, 0.02, H)]
        top = [("sph", (r.uniform(-0.1, 0.1), r.uniform(-0.2, 0.2), n * H - 0.08 + 0.01 * j), 0.07, 1) for j in range(6)]
        return mesh_object(f"CrateStackFactory({i}).spawn_asset({i})", [(pl, body), (veg, top)], bevel=False)


class MopBucketFactory:
    """A yellow mop bucket with a wringer and a mop leaning in it (floor item, front +X)."""
    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        y = fl._flat("ir_mop_yellow", (0.9, 0.75, 0.1), 0.45); grey = fl._flat("ir_mop_grey", (0.55, 0.57, 0.6), 0.4, 0.5); wood = fl._flat("ir_mop_handle", (0.7, 0.55, 0.3), 0.6, wood=True)
        return mesh_object(f"MopBucketFactory({i}).spawn_asset({i})", [
            (y, [("box", 0, 0, 0.15, 0.4, 0.3, 0.3), ("box", 0.22, 0, 0.3, 0.12, 0.3, 0.04)]),
            (grey, [("box", -0.1, 0, 0.32, 0.12, 0.2, 0.05)]),
            (wood, [("cyl", (-0.12, 0, 0.3), (-0.3, 0.02, 1.25), 0.012, 8), ("sph", (-0.12, 0, 0.32), 0.07, 1)])], bevel=False)


class BusCartFactory:
    """A grey tray-clearing cart with two shelves of white plates, cups and a tray (front +X); a food-court staple."""
    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        r = self.r
        grey = fl._flat("ir_bus_grey", (0.5, 0.52, 0.55), 0.4, 0.6); white = fl._flat("ir_plate_white", (0.9, 0.9, 0.88), 0.25); tray = fl._flat("ir_bus_tray", (0.2, 0.2, 0.22), 0.5)
        posts = [("cyl", (sx * 0.2, sy * 0.35, 0.0), (sx * 0.2, sy * 0.35, 0.95), 0.015, 8) for sx in (1, -1) for sy in (1, -1)]
        shelves = [("box", 0, 0, z, 0.5, 0.8, 0.03) for z in (0.2, 0.55, 0.9)]
        dishes = [("cyl", (r.uniform(-0.12, 0.12), y, z + 0.015), (r.uniform(-0.12, 0.12), y, z + 0.02 + 0.02 * r.randint(0, 3)), 0.09, 12)
                  for z in (0.2 + 0.015, 0.55 + 0.015) for y in (-0.25, 0.0, 0.25) if r.random() < 0.8]
        return mesh_object(f"BusCartFactory({i}).spawn_asset({i})", [(grey, posts + shelves), (white, dishes), (tray, [("box", 0, 0, 0.93, 0.4, 0.6, 0.02)])], bevel=False)
