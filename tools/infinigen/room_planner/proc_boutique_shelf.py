"""Boutique shelf stock (S15 r27 CNT-04: bare narrow shelving beside the fitting cubicles): small things that stand on a wall-gondola shelf.
  FoldedGarmentFactory  a stack of 2-4 folded garments, 0.30 x 0.38 m, 2 alternating colours
  ShoeBoxFactory        a lidded shoe box 0.32 x 0.2 x 0.12 m in a muted colour with a lighter lid band
  HandbagFactory        a small structured bag 0.28 x 0.1 x 0.2 m with a strap loop
Front +X (as the merch placer expects: x = depth, y = width).
"""
from __future__ import annotations

import random

from room_planner import proc_boutique_flagship as fl
from room_planner.proc_boutique_flagship import mesh_object

CLOTH = {"denim": (0.15, 0.22, 0.38), "camel": (0.55, 0.4, 0.25), "cream": (0.8, 0.75, 0.65), "charcoal": (0.12, 0.12, 0.13), "olive": (0.3, 0.33, 0.2), "rust": (0.5, 0.2, 0.1), "denim_light": (0.3, 0.4, 0.55)}
BOX = ((0.78, 0.72, 0.62), (0.2, 0.22, 0.26), (0.62, 0.35, 0.3), (0.85, 0.82, 0.78), (0.3, 0.38, 0.33))


class FoldedGarmentFactory:
    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        r = self.r; ks = list(CLOTH); cols = [r.choice(ks), r.choice(ks)]
        d, w = r.uniform(0.28, 0.34), r.uniform(0.5, 0.62); z = 0.0; per = {}
        for li in range(r.randint(3, 6)):
            th = r.uniform(0.04, 0.06); per.setdefault(cols[li % 2], []).append(("box", r.uniform(-0.006, 0.006), r.uniform(-0.006, 0.006), z + th / 2, d, w, th, r.uniform(-0.03, 0.03))); z += th
        return mesh_object(f"FoldedGarmentFactory({i}).spawn_asset({i})", [(fl._flat(f"ir_gar_fabric_{k}", CLOTH[k], 0.85), p) for k, p in per.items()], bevel=False)


class ShoeBoxFactory:
    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        r = self.r; c = r.choice(BOX); d, w, h = 0.2, r.uniform(0.3, 0.34), r.uniform(0.11, 0.13)
        body = fl._flat(f"ir_shoebox_{int(c[0] * 100)}_{int(c[1] * 100)}", c, 0.7); lid = fl._flat(f"ir_shoebox_lid_{int(c[0] * 100)}", tuple(min(1.0, v + 0.12) for v in c), 0.65)
        bp, lp = [], []
        for k in range(r.choice((1, 2, 2))):                                  # two boxes stacked more often than one: the shelf reads stocked, not spotted with single items
            z = k * h; bp.append(("box", 0, 0, z + h * 0.4, d, w, h * 0.8)); lp.append(("box", 0, 0, z + h * 0.9, d + 0.006, w + 0.006, h * 0.2))
        return mesh_object(f"ShoeBoxFactory({i}).spawn_asset({i})", [(body, bp), (lid, lp)], bevel=False)


class HandbagFactory:
    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        r = self.r; c = r.choice(((0.45, 0.3, 0.2), (0.1, 0.1, 0.11), (0.7, 0.62, 0.5), (0.5, 0.15, 0.15))); w, d, h = r.uniform(0.24, 0.3), 0.1, r.uniform(0.17, 0.22)
        leather = fl._flat(f"ir_bag_{int(c[0] * 100)}_{int(c[1] * 100)}", c, 0.55)
        strap = [("box", 0, -w * 0.25, h + 0.05, 0.012, 0.012, 0.1), ("box", 0, w * 0.25, h + 0.05, 0.012, 0.012, 0.1), ("box", 0, 0, h + 0.1, 0.012, w * 0.5 + 0.012, 0.012)]
        return mesh_object(f"HandbagFactory({i}).spawn_asset({i})", [(leather, [("box", 0, 0, h / 2, d, w, h)] + strap)], bevel=False)
