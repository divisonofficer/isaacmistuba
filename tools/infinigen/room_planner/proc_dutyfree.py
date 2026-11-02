"""Props for the airport duty-free hall (reference set airport_duty_free_01; docs/airport_duty_free_design_proposal.md). Flag ROOM_DUTYFREE=1.

Factory-shaped like proc_museum (Cls(seed).spawn_asset(i), front +X, origin at the bottom centre, one merged mesh). No real brands, no text: signs are plain coloured
light boxes in invented palettes.

  TreeColumnFactory     a white branching column: trunk r 0.35, four arms splaying to a flat head (height 7 m)
  IslandBoothFactory    a 5 x 3 m island shop: curved-look white counter, glowing display boxes with bottle rows, a sign ring on four posts
  EscalatorFactory      one lane 1.1 m wide, 9 m long, rising 4.5 m (front +X is the uphill direction), glass balustrades + black handrails
  CartRackFactory       a trolley rack: 6 stacked wire carts 2.2 x 0.6 m
  PlanterFactory        a low white planter 2.4 x 1.2 m with a green mass
  YellowSignFactory     a yellow direction board 0.9 x 1.4 m on a post, dark arrow bars (no lettering)
  WhiteBinFactory       a white bin with four round holes
"""
from __future__ import annotations

import math
import random

from room_planner import proc_boutique_flagship as fl
from room_planner.proc_boutique_flagship import mesh_object
from room_planner.proc_museum import _emit

BRANDS = ((1.0, 0.35, 0.6), (0.2, 0.85, 0.85), (1.0, 0.75, 0.25), (0.6, 0.45, 1.0), (0.95, 0.95, 0.9))     # invented palettes: pink, teal, gold, violet, white


class TreeColumnFactory:
    H = 7.0

    def __init__(self, seed):
        self.seed = seed

    def spawn_asset(self, i):
        white = fl._flat("ir_df_column_white", (0.9, 0.88, 0.84), 0.45)
        trunk = [("cyl", (0, 0, 0), (0, 0, 3.4), 0.35, 20)]
        arms = [("cyl", (0, 0, 3.4), (0.9 * math.cos(a), 0.9 * math.sin(a), 5.6), 0.14, 10) for a in (k * math.pi / 2 + math.pi / 4 for k in range(4))]
        head = [("box", 0, 0, 5.75, 2.4, 2.4, 0.3, math.pi / 4), ("cyl", (0, 0, 5.9), (0, 0, self.H), 0.5, 16)]
        return mesh_object(f"TreeColumnFactory({self.seed}).spawn_asset({i})", [(white, trunk + arms + head)], bevel=False)


class IslandBoothFactory:
    def __init__(self, seed):
        self.seed = seed

    def spawn_asset(self, i):
        r = random.Random(self.seed * 13 + i); rgb = BRANDS[r.randrange(len(BRANDS))]
        white = fl._flat("ir_df_counter_white", (0.92, 0.92, 0.9), 0.3); dark = fl._flat("ir_df_booth_dark", (0.06, 0.06, 0.07), 0.4, 0.4)
        glow = _emit(f"ir_df_sign_{int(rgb[0] * 9)}{int(rgb[1] * 9)}{int(rgb[2] * 9)}", rgb, 6.0); case = _emit("ir_df_case_glow", (1.0, 0.95, 0.85), 3.0)
        bottle = fl._flat("ir_df_bottle", (0.8, 0.55, 0.3), 0.15, 0.2)
        W, D = 5.0, 3.0
        counter = [("box", 0, 0, 0.5, D - 0.4, W - 0.4, 1.0), ("box", 0, 0, 1.03, D, W, 0.06)]
        cases = [("box", 0.0, y, 1.5, D * 0.5, 0.9, 0.9) for y in (-1.8, -0.6, 0.6, 1.8)]
        bottles = [("cyl", (bx, y + dy, 1.05), (bx, y + dy, 1.28), 0.035, 8) for y in (-1.8, -0.6, 0.6, 1.8) for dy in (-0.3, 0.0, 0.3) for bx in (-0.3, 0.0, 0.3)]
        posts = [("cyl", (sx * D * 0.45, sy * W * 0.45, 1.06), (sx * D * 0.45, sy * W * 0.45, 3.6), 0.04, 8) for sx in (-1, 1) for sy in (-1, 1)]
        ring = [("box", 0, 0, 3.7, D * 0.95, W * 0.95, 0.5)]
        return mesh_object(f"IslandBoothFactory({self.seed}).spawn_asset({i})", [(white, counter), (case, cases), (bottle, bottles), (dark, posts), (glow, ring)], bevel=False)


class EscalatorFactory:
    LEN, RISE = 9.0, 4.5

    def __init__(self, seed):
        self.seed = seed

    def spawn_asset(self, i):
        steel = fl._flat("ir_df_esc_steel", (0.55, 0.57, 0.6), 0.35, 0.8); black = fl._flat("ir_df_handrail", (0.02, 0.02, 0.02), 0.5)
        glass = fl._flat("ir_df_esc_glass", (0.75, 0.85, 0.85), 0.05)
        n = 24; run = self.LEN / n; rise = self.RISE / n
        steps = [("box", -self.LEN / 2 + (k + 0.5) * run, 0, (k + 0.5) * rise, run, 1.0, rise) for k in range(n)]
        incline = math.atan2(self.RISE, self.LEN)
        glass_p, rail = [], []
        for sy in (-1, 1):
            for k in range(n):
                glass_p.append(("box", -self.LEN / 2 + (k + 0.5) * run, sy * 0.58, (k + 0.5) * rise + 0.55, run, 0.02, 1.1))
            rail.append(("cyl", (-self.LEN / 2, sy * 0.58, 1.12), (self.LEN / 2, sy * 0.58, 1.12 + self.RISE), 0.04, 8))
        return mesh_object(f"EscalatorFactory({self.seed}).spawn_asset({i})", [(steel, steps), (glass, glass_p), (black, rail)], bevel=False)


class CartRackFactory:
    def __init__(self, seed):
        self.seed = seed

    def spawn_asset(self, i):
        steel = fl._flat("ir_df_cart_steel", (0.6, 0.62, 0.65), 0.3, 0.9)
        parts = []
        for k in range(6):
            x = -0.9 + k * 0.32; z = 0.5 + k * 0.01
            parts += [("box", x, 0, z + 0.2, 0.55, 0.55, 0.02), ("cyl", (x, -0.27, z + 0.2), (x, -0.27, z + 0.9), 0.012, 6), ("cyl", (x, 0.27, z + 0.2), (x, 0.27, z + 0.9), 0.012, 6)]
        parts.append(("box", 0, 0, 0.12, 2.2, 0.6, 0.04))
        return mesh_object(f"CartRackFactory({self.seed}).spawn_asset({i})", [(steel, parts)], bevel=False)


class PlanterFactory:
    def __init__(self, seed):
        self.seed = seed

    def spawn_asset(self, i):
        white = fl._flat("ir_df_planter", (0.9, 0.9, 0.88), 0.4); green = fl._flat("ir_df_foliage", (0.12, 0.35, 0.12), 0.8)
        r = random.Random(self.seed * 5 + i)
        bush = [("sph", (r.uniform(-0.9, 0.9), r.uniform(-0.3, 0.3), 0.75 + r.uniform(0, 0.2)), r.uniform(0.35, 0.5), 2) for _ in range(6)]
        return mesh_object(f"PlanterFactory({self.seed}).spawn_asset({i})", [(white, [("box", 0, 0, 0.25, 1.2, 2.4, 0.5)]), (green, bush)], bevel=False)


class YellowSignFactory:
    def __init__(self, seed):
        self.seed = seed

    def spawn_asset(self, i):
        yel = _emit("ir_df_sign_yellow", (1.0, 0.78, 0.05), 1.2); dark = fl._flat("ir_df_sign_dark", (0.04, 0.04, 0.04), 0.5)
        r = random.Random(self.seed * 3 + i)
        bars = [("box", 0.025, r.uniform(-0.12, 0.12), 2.2 + 0.28 * k, 0.01, r.uniform(0.35, 0.65), 0.07) for k in range(4)]
        return mesh_object(f"YellowSignFactory({self.seed}).spawn_asset({i})", [(dark, [("cyl", (0, 0, 0), (0, 0, 1.6), 0.04, 8)] + bars), (yel, [("box", 0, 0, 2.5, 0.04, 0.9, 1.4)])], bevel=False)


class WhiteBinFactory:
    def __init__(self, seed):
        self.seed = seed

    def spawn_asset(self, i):
        white = fl._flat("ir_df_bin_white", (0.93, 0.93, 0.92), 0.4); dark = fl._flat("ir_df_bin_hole", (0.03, 0.03, 0.03), 0.6)
        holes = [("cyl", (0.28, y, z), (0.31, y, z), 0.06, 12) for y in (-0.12, 0.12) for z in (0.55, 0.85)]
        return mesh_object(f"WhiteBinFactory({self.seed}).spawn_asset({i})", [(white, [("box", 0, 0, 0.5, 0.55, 0.55, 1.0)]), (dark, holes)], bevel=False)
