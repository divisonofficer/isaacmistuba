"""Props for the LP-cafe building lounge (S29; refs out/room_planner_refs/lounge_lp_cafe_01_clean; docs/lounge_lp_cafe_design_proposal.md). Front +X, back at x = 0 for wall pieces.

  LpShelfWallFactory   a dark-wood grid shelving unit 2.4 m wide x 0.38 deep x 2.3 high: 6 columns x 6 rows of cells, rows of LP sleeves (12 colours) standing in most cells, a vertical warm LED strip in every
                       second divider; two or more units side by side make the LP wall
  RedHighTableFactory  a long red lacquered high table 3.0 x 0.7 x 1.05 m with a lower foot rail
  WoodStoolFactory     a bar stool: round oak seat, four slim legs and a ring foot rest, seat height 0.76 m
"""
from __future__ import annotations

import math
import random

import bpy

from room_planner import proc_assets as pa
from room_planner import proc_building as pb
from room_planner.proc_boutique_flagship import mesh_object
from room_planner import proc_boutique_flagship as fl

SLEEVE = ((0.08, 0.08, 0.09), (0.55, 0.12, 0.1), (0.9, 0.82, 0.62), (0.15, 0.3, 0.5), (0.85, 0.55, 0.15), (0.3, 0.45, 0.3), (0.75, 0.75, 0.72), (0.4, 0.25, 0.15), (0.9, 0.9, 0.88), (0.2, 0.2, 0.35),
          (0.7, 0.3, 0.4), (0.6, 0.55, 0.45))


class LpShelfWallFactory:
    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        r = self.r
        wood = fl._flat("ir_lp_wood", (0.36, 0.22, 0.12), 0.5, wood=True); dark = fl._flat("ir_lp_back", (0.06, 0.05, 0.05), 0.7); led = pb._emit("ir_lp_led", (1.0, 0.75, 0.42), 6.0)
        W, D, H = 3.0, 0.45, 2.7; nc, nr = 6, 7; cw = W / nc; ch = (H - 0.1) / nr
        frame = [("box", D / 2, 0, 0.05, D, W, 0.1), ("box", D / 2, 0, H - 0.02, D, W, 0.04)] + [("box", D / 2, -W / 2 + k * cw, H / 2, D, 0.03, H) for k in range(nc + 1)] + \
                [("box", D / 2, 0, 0.1 + k * ch, D, W, 0.025) for k in range(nr + 1)]
        back = [("box", 0.01, 0, H / 2, 0.02, W, H)]
        strips = [("box", D * 0.92, -W / 2 + k * cw, H / 2, 0.012, 0.012, H - 0.15) for k in range(1, nc, 2)]
        sleeves = {}
        for rw in range(nr):
            for cl in range(nc):
                if r.random() < 0.12:
                    continue                                          # an empty cell
                n = r.randint(7, 13); y = -W / 2 + cl * cw + 0.045
                for q in range(n):
                    c = r.choice(SLEEVE); t = 0.0045
                    sleeves.setdefault(c, []).append(("box", D * 0.52, y + q * (cw - 0.09) / n, 0.1 + rw * ch + 0.17 + 0.012, 0.3, t, 0.31, r.uniform(-0.06, 0.06)))
        # listening posts (S29F r6 refs: dark wide posts carrying black over-ear headphones with a white control box under each): a post at the left end and the middle divider
        blk = fl._flat("ir_lp_phone", (0.03, 0.03, 0.035), 0.45); wht = fl._flat("ir_lp_ctrl", (0.85, 0.85, 0.82), 0.4)
        posts, phones, ctrls = [], [], []
        for k in (0, nc // 2):                                  # the next unit's first post closes this one
            yk = -W / 2 + k * cw
            posts.append(("box", D / 2, yk, H / 2, D, 0.09, H))
            for rw in (1, 3, 5):
                z0 = 0.1 + rw * ch + 0.12
                px = D + 0.035
                phones += [("cyl", (px, yk - 0.085, z0), (px + 0.04, yk - 0.085, z0), 0.048, 14), ("cyl", (px, yk + 0.085, z0), (px + 0.04, yk + 0.085, z0), 0.048, 14),
                           ("box", px + 0.02, yk, z0 + 0.075, 0.02, 0.19, 0.016), ("box", px + 0.02, yk - 0.09, z0 + 0.04, 0.02, 0.016, 0.07), ("box", px + 0.02, yk + 0.09, z0 + 0.04, 0.02, 0.016, 0.07)]
                ctrls += [("box", D + 0.02, yk, z0 - 0.17, 0.035, 0.085, 0.15)]
        groups = [(wood, frame), (dark, back), (led, strips), (dark, posts), (blk, phones), (wht, ctrls)] + [(fl._flat(f"ir_lp_sleeve_{int(c[0] * 100)}_{int(c[1] * 100)}_{int(c[2] * 100)}", c, 0.5), ps) for c, ps in sleeves.items()]
        o = mesh_object(f"LpShelfWallFactory({i}).spawn_asset({i})", groups, bevel=False)
        # the wall lights its own sleeves (S29 r5, user: 'the LP display should be much bigger and carry lights'): three tall warm area lights in front of every second divider
        for k in (1, 3, 5):
            ld = bpy.data.lights.new(f"ir_lp_light_{i}_{k}", "AREA"); ld.shape = "RECTANGLE"; ld.size = 0.12; ld.size_y = H - 0.4; ld.energy = 55.0; ld.color = (1.0, 0.72, 0.4)
            lo = bpy.data.objects.new(f"PointLampFactory(lp).spawn_asset({i}_{k})", ld); bpy.context.scene.collection.objects.link(lo); lo.parent = o
            lo.location = (D + 0.04, -W / 2 + k * cw, H / 2); lo.rotation_euler = (0, math.pi / 2, 0)
        return o


class RedHighTableFactory:
    def __init__(self, seed):
        self.r = random.Random(seed); self.L = self.r.choice((2.4, 3.0, 3.6))

    def spawn_asset(self, i):
        red = fl._flat("ir_lounge_red", (0.55, 0.08, 0.06), 0.35); L = self.L
        top = [("box", 0, 0, 1.03, 0.7, L, 0.04)]
        legs = [("box", sx * 0.3, sy * (L / 2 - 0.06), 0.5, 0.05, 0.05, 1.0) for sx in (1, -1) for sy in (1, -1)] + [("box", sx * 0.3, 0, 0.25, 0.03, L - 0.12, 0.03) for sx in (1, -1)]
        # S29 r3 CNT-01: bare tops -> cups on saucers, a few LP sleeves leaning on the table, a small amber candle jar, a napkin holder
        cup = fl._flat("ir_lounge_cup", (0.9, 0.88, 0.82), 0.3); cof = fl._flat("ir_lounge_coffee", (0.12, 0.07, 0.04), 0.3); lp = fl._flat("ir_lounge_lp", (0.07, 0.07, 0.08), 0.4)
        sl = fl._flat("ir_lounge_sleeve", (0.82, 0.74, 0.55), 0.5); amber = fl._flat("ir_lounge_candle", (0.9, 0.55, 0.2), 0.4)
        cups, coff, lps, sleeves, amb = [], [], [], [], []
        n_ = max(2, round(L / 0.8))
        for k in range(n_):
            y = (k - (n_ - 1) / 2) * 0.8
            for sx in (-1, 1):
                if self.r.random() < 0.3:
                    continue
                x = sx * 0.22
                cups += [("cyl", (x, y, 1.05), (x, y, 1.062), 0.055, 12), ("cyl", (x, y, 1.062), (x, y, 1.115), 0.033, 10)]
                coff.append(("cyl", (x, y, 1.112), (x, y, 1.116), 0.028, 10))
        for k in range(max(1, round(L / 1.5))):
            y = (k - (max(1, round(L / 1.5)) - 1) / 2) * 1.5 + 0.35
            amb.append(("cyl", (0, y, 1.05), (0, y, 1.1), 0.035, 10))
            lps.append(("box", 0.0, y - 0.35, 1.19, 0.006, 0.3, 0.3)); sleeves.append(("box", 0.0, y - 0.35, 1.19, 0.01, 0.31, 0.31, 0.0))
        # a turntable (S29F: 'turntables on the red tables'): dark plinth, steel platter with a black record and a red label, tonearm, two knobs; one per 2.4 m of table, at a free spot
        ply = fl._flat("ir_tt_plinth", (0.05, 0.05, 0.055), 0.35); stl = fl._flat("ir_tt_steel", (0.7, 0.7, 0.72), 0.25, 0.9); lab = fl._flat("ir_tt_label", (0.65, 0.1, 0.08), 0.5)
        tp, tpl, trc, tlb, tarm = [], [], [], [], []
        for k in range(max(1, round(L / 2.4))):
            ty = (k - (max(1, round(L / 2.4)) - 1) / 2) * 2.4 - 0.55 + (0.0 if L < 3.0 else 0.0)
            tp.append(("box", 0.0, ty, 1.07, 0.34, 0.44, 0.04))
            tpl += [("cyl", (-0.02, ty, 1.09), (-0.02, ty, 1.098), 0.15, 24)]
            trc += [("cyl", (-0.02, ty, 1.098), (-0.02, ty, 1.101), 0.14, 28)]
            tlb += [("cyl", (-0.02, ty, 1.101), (-0.02, ty, 1.103), 0.04, 14)]
            tarm += [("box", 0.12, ty + 0.17, 1.12, 0.012, 0.012, 0.02), ("box", 0.05, ty + 0.12, 1.112, 0.2, 0.012, 0.008, 0.5)]
            tp += [("box", 0.14, ty - 0.18, 1.1, 0.03, 0.03, 0.03), ("box", 0.14, ty - 0.12, 1.1, 0.03, 0.03, 0.03)]
        return mesh_object(f"RedHighTableFactory({i}).spawn_asset({i})", [(red, top + legs), (cup, cups), (cof, coff), (lp, lps), (amber, amb), (ply, tp), (stl, tpl + tarm), (lp, trc), (lab, tlb)], bevel=False)


class WoodStoolFactory:
    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        oak = fl._flat("ir_stool_oak", (0.62, 0.45, 0.28), 0.5, wood=True)
        parts = [("cyl", (0, 0, 0.745), (0, 0, 0.77), 0.2, 20)] + [("cyl", (sx * 0.14, sy * 0.14, 0.0), (sx * 0.19, sy * 0.19, 0.745), 0.016, 8) for sx in (1, -1) for sy in (1, -1)] + \
                [("cyl", (0, 0, 0.27), (0, 0, 0.285), 0.17, 20)]
        return mesh_object(f"WoodStoolFactory({i}).spawn_asset({i})", [(oak, parts)], bevel=False)


class RedHighTableLongFactory(RedHighTableFactory):
    """The LP-lounge reference plan (user 2026-10-20): two LONG red high tables, 4.8 m, with a row of oak stools on both sides. Same table, fixed length."""

    def __init__(self, seed):
        super().__init__(seed); self.L = 4.8
