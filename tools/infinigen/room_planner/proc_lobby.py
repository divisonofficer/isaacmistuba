"""Props for the tall building lobby (S30; refs out/room_planner_refs/lobby_tower_01: a Codex plan + 8 views of a glass-fronted corporate lobby: polished tan stone floor, warm cove light, leather lounge
benches, a glass-walled cafe, an exhibition corridor with digital wall displays, a pixel-mosaic art panel). Front +X, back at x = 0 for wall pieces.

  LeatherBenchFactory     a backless lounge bench 2.4 x 0.75 x 0.45 m: warm brown leather slab on a dark recessed base (a quarter of them 1.6 m)
  DisplayWallFactory      a wall display band 5.0 x 0.08 x 1.8 m: black frame, 5-8 emissive screens of different widths showing blocks of blue / orange / white 'content'
  MosaicPanelFactory      a pixel-mosaic art panel 1.7 x 0.08 x 2.6 m: a 12 x 18 grid of small olive / green / yellow-green tiles
  RevolvingDoorFactory    a revolving door drum, 2.8 m across, 2.9 high: ring rails, four glass wings, steel posts, glass canopy
  GlassCafeBoxFactory     a glass-walled cafe box 8.0 x 4.5 x 3.6 m: steel frame, glass panes, a warm back shelf wall with bottles / objects, a counter
"""
from __future__ import annotations

import math
import random

import bpy

from room_planner import proc_assets as pa
from room_planner import proc_boutique_flagship as fl
from room_planner import proc_building as pb
from room_planner.proc_boutique_flagship import mesh_object


class LeatherBenchFactory:
    def __init__(self, seed):
        self.r = random.Random(seed); self.L = self.r.choice((2.4, 2.4, 2.4, 1.6))

    def spawn_asset(self, i):
        t = self.r.uniform(0.85, 1.1)
        leather = fl._flat("ir_lobby_leather", (0.42 * t, 0.2 * t, 0.085 * t), 0.45); base = fl._flat("ir_lobby_base", (0.06, 0.055, 0.05), 0.5)
        return mesh_object(f"LeatherBenchFactory({i}).spawn_asset({i})", [(leather, [("box", 0, 0, 0.32, 0.75, self.L, 0.26)]), (base, [("box", 0, 0, 0.1, 0.62, self.L - 0.14, 0.2)])], bevel=True)


class DisplayWallFactory:
    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        r = self.r; W, H = 5.0, 1.8
        frame = fl._flat("ir_dw_frame", (0.04, 0.04, 0.045), 0.4)
        parts = [("box", 0.035, 0, H / 2, 0.07, W, H)]
        groups = [(frame, parts)]
        scr = {}
        n = r.randint(5, 8); w_ = (W - 0.2) / n; y = -W / 2 + 0.1
        pal = ((0.1, 0.35, 0.9), (0.95, 0.5, 0.15), (0.85, 0.9, 1.0), (0.2, 0.2, 0.35), (0.1, 0.6, 0.7))
        for k in range(n):
            ww = w_ * r.uniform(0.75, 0.95); c = r.choice(pal)
            scr.setdefault(c, []).append(("box", 0.075, y + ww / 2, H / 2, 0.006, ww, H - 0.2))
            for _ in range(r.randint(2, 4)):                                   # blocks of 'content' on the screen
                bw, bh = ww * r.uniform(0.25, 0.7), r.uniform(0.15, 0.5); cc = r.choice(pal)
                scr.setdefault(cc, []).append(("box", 0.08, y + r.uniform(0.1, ww - 0.1), r.uniform(0.3, H - 0.4), 0.004, bw, bh))
            y += w_
        for c, ps in scr.items():
            groups.append((pb._emit(f"ir_dw_screen_{int(c[0] * 100)}_{int(c[1] * 100)}_{int(c[2] * 100)}", c, 1.6), ps))
        return mesh_object(f"DisplayWallFactory({i}).spawn_asset({i})", groups, bevel=False)


class MosaicPanelFactory:
    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        r = self.r; W, H = 1.7, 2.6; nc, nr = 12, 18; cw, ch = W / nc, H / nr
        back = fl._flat("ir_mos_back", (0.05, 0.06, 0.04), 0.6)
        groups = [(back, [("box", 0.03, 0, H / 2 + 0.2, 0.06, W, H)])]
        tiles = {}
        for a in range(nc):
            for b in range(nr):
                s = r.random() ** 0.8; g = (0.12 + 0.35 * s, 0.2 + 0.32 * s, 0.03 + 0.06 * s)
                g = tuple(round(v, 2) for v in g)
                tiles.setdefault(g, []).append(("box", 0.07 + 0.02 * r.random(), -W / 2 + (a + 0.5) * cw, 0.2 + (b + 0.5) * ch, 0.04, cw * 0.9, ch * 0.9))
        for g, ps in tiles.items():
            groups.append((fl._flat(f"ir_mos_{int(g[0] * 100)}_{int(g[1] * 100)}", g, 0.5), ps))
        return mesh_object(f"MosaicPanelFactory({i}).spawn_asset({i})", groups, bevel=False)


class RevolvingDoorFactory:
    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        steel = fl._flat("ir_rev_steel", (0.62, 0.63, 0.66), 0.25, 1.0); glass = pa._flat("ir_rev_glass", (0.9, 0.95, 0.97), 0.02, transmission=0.9)
        R, H = 1.4, 2.9; parts = []
        parts += [("cyl", (0, 0, 0.0), (0, 0, 0.05), R, 28), ("cyl", (0, 0, H - 0.08), (0, 0, H), R, 28), ("cyl", (0, 0, 0.0), (0, 0, H), 0.05, 10)]
        for k in range(4):
            a = math.radians(45 + 90 * k)
            parts.append(("box", math.cos(a) * R * 0.5, math.sin(a) * R * 0.5, H / 2, R * 0.98, 0.04, H - 0.2, a))
        panes = [("box", math.cos(math.radians(45 + 90 * k)) * R * 0.5, math.sin(math.radians(45 + 90 * k)) * R * 0.5, H / 2, R * 0.9, 0.012, H - 0.35, math.radians(45 + 90 * k)) for k in range(4)]
        return mesh_object(f"RevolvingDoorFactory({i}).spawn_asset({i})", [(steel, parts), (glass, panes)], bevel=False)


class GlassCafeBoxFactory:
    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        r = self.r; L, D, H = 8.0, 4.5, 3.6
        steel = fl._flat("ir_cafe_steel", (0.1, 0.1, 0.11), 0.35, 0.8); glass = pa._flat("ir_cafe_glass", (0.9, 0.95, 0.97), 0.02, transmission=0.9)
        wood = fl._flat("ir_cafe_wood", (0.5, 0.33, 0.18), 0.5, wood=True); warm = pb._emit("ir_cafe_warm", (1.0, 0.7, 0.4), 2.2); dark = fl._flat("ir_cafe_dark", (0.06, 0.05, 0.05), 0.6)
        posts = [("box", sx * D / 2 * 0 + (0.0 if sx == 0 else 0), y, H / 2, 0.06, 0.06, H) for sx in (0,) for y in [-L / 2 + k * L / 4 for k in range(5)]]
        posts += [("box", D, y, H / 2, 0.06, 0.06, H) for y in [-L / 2 + k * L / 4 for k in range(5)]]
        rails = [("box", 0.0, 0, 0.03, 0.06, L, 0.06), ("box", 0.0, 0, H - 0.03, 0.06, L, 0.06), ("box", D, 0, H - 0.03, 0.06, L, 0.06), ("box", D / 2, -L / 2, H - 0.03, D, 0.06, 0.06), ("box", D / 2, L / 2, H - 0.03, D, 0.06, 0.06)]
        panes = [("box", 0.0, 0, H / 2, 0.01, L - 0.1, H - 0.2), ("box", D / 2, -L / 2, H / 2, D - 0.1, 0.01, H - 0.2), ("box", D / 2, L / 2, H / 2, D - 0.1, 0.01, H - 0.2)]
        back = [("box", D - 0.15, 0, H / 2, 0.1, L - 0.2, H - 0.1)]
        shelves = [("box", D - 0.3, 0, 0.9 + 0.55 * k, 0.28, L - 0.4, 0.04) for k in range(5)]
        objs = [("box", D - 0.3, -L / 2 + 0.4 + r.random() * (L - 0.8), 0.95 + 0.55 * r.randint(0, 4), 0.14, r.uniform(0.1, 0.3), r.uniform(0.18, 0.4)) for _ in range(36)]
        counter = [("box", 1.2, 0, 0.55, 0.7, L * 0.6, 1.1)]
        return mesh_object(f"GlassCafeBoxFactory({i}).spawn_asset({i})", [(steel, posts + rails), (glass, panes), (dark, back), (wood, shelves + counter), (warm, objs)], bevel=False)
