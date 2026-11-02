"""Props for the university cafeteria (S27; refs out/room_planner_refs/cafeteria_school_01_clean; docs/cafeteria_school_design_proposal.md). Front +X.

  PlywoodShellChairFactory  a moulded light-plywood chair: a single bent shell (seat + back, 0.45 x 0.5 x 0.82, seat 0.45 m) with a handle cut-out in the back and four slim splayed oak legs
  LongOakTableFactory       a long light-oak canteen table 3.6 x 0.9 x 0.75 m (top 4 cm, square legs, a side rail)
  UvTrapColumnFactory       a square concrete / cream-plaster column (0.7 x 0.7 x full height 3.0) with a glowing blue UV insect-trap panel at 2.3 m and a wall socket
  ServingLineFactory        a cafeteria serving counter 6.0 x 0.9 x 0.95 m: dark wood front, stainless top with 4 hot-food wells (coloured food in them), a tray rail on the guest side and a glass sneeze guard
"""
from __future__ import annotations

import math
import random

from room_planner import proc_assets as pa
from room_planner import proc_building as pb
from room_planner import proc_boutique_flagship as fl
from room_planner.proc_boutique_flagship import mesh_object


class PlywoodShellChairFactory:
    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        ply = fl._flat("ir_ply_shell", (0.78, 0.6, 0.38), 0.45, wood=True); leg = fl._flat("ir_ply_leg", (0.7, 0.52, 0.3), 0.5, wood=True); dk = fl._flat("ir_ply_cut", (0.06, 0.05, 0.05), 0.6)
        seat = [("box", 0.0, 0.0, 0.45, 0.45, 0.47, 0.03)]
        back = [("box", -0.21, 0.0, 0.68, 0.03, 0.44, 0.4, 0.0)]
        legs = [("cyl", (sx * 0.17, sy * 0.19, 0.0), (sx * 0.2, sy * 0.22, 0.44), 0.014, 8) for sx in (1, -1) for sy in (1, -1)]
        cut = [("box", -0.222, 0.0, 0.8, 0.012, 0.12, 0.03)]
        return mesh_object(f"PlywoodShellChairFactory({i}).spawn_asset({i})", [(ply, seat + back), (leg, legs), (dk, cut)], bevel=True)


class LongOakTableFactory:
    def __init__(self, seed):
        self.r = random.Random(seed); self.L = self.r.choice((3.0, 3.6, 4.2))

    def spawn_asset(self, i):
        L = self.L
        oak = fl._flat("ir_canteen_oak", (0.74, 0.55, 0.32), 0.4, wood=True); leg = fl._flat("ir_canteen_leg", (0.55, 0.38, 0.2), 0.5, wood=True)
        top = [("box", 0, 0, 0.73, 0.9, L, 0.04)]
        legs = [("box", sx * 0.38, sy * (L / 2 - 0.12), 0.355, 0.07, 0.07, 0.71) for sx in (1, -1) for sy in (1, -1)] + [("box", 0, 0, 0.62, 0.05, L - 0.3, 0.08)]
        # school-canteen tableware (S27 r4 CNT-01: bare tops): a grey tray with a plate and a cup at ~75 % of the seats, napkin + salt holders down the middle
        tray = fl._flat("ir_canteen_tray", (0.3, 0.4, 0.5), 0.5); plate = fl._flat("ir_canteen_plate", (0.93, 0.93, 0.9), 0.3); cup = fl._flat("ir_canteen_cup", (0.85, 0.88, 0.92), 0.35)
        food = fl._flat("ir_canteen_food", (0.7, 0.45, 0.2), 0.6); holder = fl._flat("ir_canteen_holder", (0.72, 0.72, 0.74), 0.3, 1.0)
        trays, plates, cups, foods, holders = [], [], [], [], []
        for n_ in range(round(L / 0.9)):
            y = (n_ - (round(L / 0.9) - 1) / 2) * 0.9
            for sx in (-1, 1):
                if self.r.random() < 0.25:
                    continue
                x, z = sx * 0.2, 0.75
                trays.append(("box", x, y, z + 0.01, 0.32, 0.42, 0.02, self.r.uniform(-0.08, 0.08)))
                plates.append(("cyl", (x - sx * 0.02, y - 0.04, z + 0.02), (x - sx * 0.02, y - 0.04, z + 0.035), 0.1, 14))
                foods.append(("cyl", (x - sx * 0.02, y - 0.04, z + 0.035), (x - sx * 0.02, y - 0.04, z + 0.05), 0.07, 10))
                cups.append(("cyl", (x + sx * 0.06, y + 0.15, z + 0.02), (x + sx * 0.06, y + 0.15, z + 0.1), 0.035, 10))
        for n_ in range(max(1, round(L / 1.8))):
            y = (n_ - (max(1, round(L / 1.8)) - 1) / 2) * 1.8
            holders += [("box", 0, y - 0.08, 0.8, 0.07, 0.1, 0.1), ("cyl", (0, y + 0.1, 0.75), (0, y + 0.1, 0.82), 0.02, 8)]
        return mesh_object(f"LongOakTableFactory({i}).spawn_asset({i})", [(oak, top), (leg, legs), (tray, trays), (plate, plates), (food, foods), (cup, cups), (holder, holders)], bevel=True)


class UvTrapColumnFactory:
    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        cream = fl._flat("ir_column_cream", (0.82, 0.78, 0.7), 0.7); blue = pb._emit("ir_uv_blue", (0.35, 0.55, 1.0), 14.0); frame = pa._flat("ir_uv_frame", (0.85, 0.85, 0.88), 0.4); blk = pa._flat("ir_uv_dark", (0.05, 0.05, 0.06), 0.5)
        H = 3.0
        o = mesh_object(f"UvTrapColumnFactory({i}).spawn_asset({i})",
                        [(cream, [("box", 0, 0, H / 2, 0.7, 0.7, H)]), (frame, [("box", 0.36, 0, 2.3, 0.05, 0.5, 0.28)]), (blue, [("box", 0.39, 0, 2.3, 0.006, 0.42, 0.2)]),
                         (blk, [("box", 0.36, 0.15, 0.4, 0.02, 0.08, 0.08)])], bevel=False)
        ld = pb.bpy.data.lights.new(f"ir_uv_{i}", "AREA"); ld.shape = "RECTANGLE"; ld.size = 0.4; ld.size_y = 0.2; ld.energy = 25.0; ld.color = (0.5, 0.65, 1.0)
        lo = pb.bpy.data.objects.new(f"PointLampFactory(uv).spawn_asset({i})", ld); pb.bpy.context.scene.collection.objects.link(lo); lo.parent = o; lo.location = (0.42, 0, 2.3); lo.rotation_euler = (0, math.pi / 2, 0)
        return o


class ServingLineFactory:
    def __init__(self, seed):
        self.r = random.Random(seed); self.L = self.r.choice((5.0, 6.0, 7.0))

    def spawn_asset(self, i):
        L, r = self.L, self.r
        wood = fl._flat("ir_serve_wood", (0.3, 0.18, 0.1), 0.5, wood=True); steel = fl._flat("ir_serve_steel", (0.72, 0.72, 0.74), 0.25, 1.0); dark = fl._flat("ir_serve_well", (0.1, 0.1, 0.11), 0.4, 0.8)
        glass = pa._flat("ir_serve_glass", (0.9, 0.95, 0.97), 0.03, transmission=0.9)
        body = [("box", 0.35, 0, 0.45, 0.7, L, 0.9)]; top = [("box", 0.36, 0, 0.92, 0.78, L + 0.02, 0.04)]; rail = [("cyl", (0.78, -L / 2, 0.8), (0.78, L / 2, 0.8), 0.015, 8)]
        wells, food = [("box", 0.36, 0, 0.935, 0.5, L - 0.4, 0.01)], {}
        n = 6
        for k in range(n):
            y = -L / 2 + 0.3 + (k + 0.5) * (L - 0.6) / n; c = r.choice(((0.75, 0.4, 0.15), (0.3, 0.55, 0.2), (0.8, 0.2, 0.15), (0.9, 0.8, 0.5), (0.5, 0.3, 0.15)))
            food.setdefault(c, []).append(("box", 0.36, y, 0.945, 0.4, (L - 0.6) / n - 0.12, 0.03))
        guard = [("box", 0.62, 0, 1.35, 0.01, L - 0.2, 0.4)] + [("cyl", (0.62, sy * (L / 2 - 0.1), 0.95), (0.62, sy * (L / 2 - 0.1), 1.55), 0.012, 8) for sy in (-1, 1)]
        # trays slid along the rail, a stack of plates + cups and a few finished dishes (S27 r4 CNT-04: bare counter top)
        trayc = fl._flat("ir_serve_tray", (0.3, 0.4, 0.5), 0.5); platec = fl._flat("ir_serve_plate", (0.93, 0.93, 0.9), 0.3)
        trays = [("box", 0.76, -L / 2 + 0.35 + 0.34 * k, 0.815 + 0.02 * k, 0.4, 0.3, 0.02) for k in range(4)]
        plates = [("cyl", (0.5, L / 2 - 0.25 - 0.26 * n, 0.94), (0.5, L / 2 - 0.25 - 0.26 * n, 0.94 + 0.012 * (6 + 2 * n)), 0.1, 14) for n in range(3)]
        dishes = [("cyl", (0.36, -L / 2 + 0.3 + 0.32 * k, 0.94), (0.36, -L / 2 + 0.3 + 0.32 * k, 0.956), 0.09, 12) for k in range(1, 5)]
        trays += [("box", 0.5, -L / 2 + 0.28, 0.945 + 0.014 * k, 0.4, 0.3, 0.012) for k in range(7)]                  # a stack of trays at the head of the line
        cupc = fl._flat("ir_serve_cup", (0.88, 0.9, 0.95), 0.3)
        cups = [("cyl", (0.66, -L / 2 + 0.7 + 0.12 * n, 0.94), (0.66, -L / 2 + 0.7 + 0.12 * n, 1.0), 0.032, 8) for n in range(int((L - 1.4) / 0.12))]   # drinks cups along the front edge
        for c_, ps in list(food.items()):                                                   # a heap of food on every well, not a flat slab
            ps += [("sph", (0.36, (p_[2]), 0.97), 0.1, 1) for p_ in ps[:]]
        groups = [(trayc, trays), (cupc, cups), (platec, plates + dishes)] + [(wood, body), (steel, top + rail), (dark, wells), (glass, guard[:1]), (steel, guard[1:])] + [(fl._flat(f"ir_serve_food_{int(c[0] * 100)}_{int(c[1] * 100)}", c, 0.6), ps) for c, ps in food.items()]
        return mesh_object(f"ServingLineFactory({i}).spawn_asset({i})", groups, bevel=False)
