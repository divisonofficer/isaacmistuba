"""Home bathroom fixtures (P2 apartment r1, FUN-01 x8: 'the tiled bathroom is empty, no toilet or washbasin'; the catalog only had commercial restroom pieces). Factory-shaped, front +X.

  HomeVanityFactory       a bathroom vanity (0.5 x 0.9 x 0.85 m, back at x = 0): white or oak cabinet with two drawers, a ceramic top with an inset basin, a chrome mixer tap, a round mirror above
  ShowerEnclosureFactory  a corner glass shower (0.95 x 0.95 x 2.1 m, origin at the centre): tray, glass door on the +X side and a fixed glass panel on the +Y side, rain head and mixer on the walls
"""
from __future__ import annotations

import math
import os
import random

from room_planner import proc_assets as pa
from room_planner import proc_boutique_flagship as fl
from room_planner.proc_boutique_flagship import mesh_object


class HomeVanityFactory:
    def __init__(self, seed):
        self.r = random.Random(seed); self.oak = self.r.random() < 0.5

    def spawn_asset(self, i):
        cab = fl._flat("ir_vanity_oak", (0.62, 0.45, 0.28), 0.5, wood=True) if self.oak else fl._flat("ir_vanity_white", (0.9, 0.9, 0.88), 0.35)
        top = fl._flat("ir_vanity_top", (0.92, 0.92, 0.9), 0.15); basin = fl._flat("ir_ceramic_white", (0.94, 0.94, 0.92), 0.08)
        led = fl._flat("ir_mirror_led", (1.0, 0.95, 0.85), 0.3); lb = led.node_tree.nodes["Principled BSDF"]; lb.inputs["Emission Color"].default_value = (1.0, 0.92, 0.78, 1); lb.inputs["Emission Strength"].default_value = 3.0
        chrome = fl._flat("ir_chrome", (0.8, 0.8, 0.82), 0.15, 1.0); mirror = fl._flat("ir_mirror", (0.9, 0.92, 0.93), 0.02, 1.0); frame = fl._flat("ir_mirror_frame", (0.1, 0.1, 0.1), 0.4, 0.6)
        _hv_basin, _hv_drain = _basin(0.28, 0, 0.745, 0.40, 0.50, 0.10)                  # P2b r22 GEO-01: a vessel basin with a real bowl, not a solid disc
        tray_m = fl._flat("ir_vanity_tray", (0.2, 0.17, 0.14), 0.5, wood=True); bot_m = fl._flat("ir_vanity_soap", (0.85, 0.8, 0.7), 0.3)
        extras = [(tray_m, [("box", 0.38, 0.33, 0.725, 0.12, 0.2, 0.012)]), (bot_m, [("cyl", (0.4, 0.37, 0.731), (0.4, 0.37, 0.8), 0.022, 12), ("cyl", (0.36, 0.3, 0.731), (0.36, 0.3, 0.76), 0.026, 12), ("box", 0.37, 0.4, 0.74, 0.05, 0.07, 0.02)])]   # a tray with a pump bottle and soaps
        groups = [(cab, [("box", 0.25, 0, 0.36, 0.48, 0.88, 0.62), ("box", 0.51, -0.22, 0.5, 0.012, 0.4, 0.2), ("box", 0.51, 0.22, 0.5, 0.012, 0.4, 0.2), ("box", 0.25, 0, 0.04, 0.44, 0.84, 0.08)]),
                  (top, [("box", 0.26, 0, 0.7, 0.52, 0.92, 0.04)]),
                  (basin, _hv_basin),
                  (chrome, [("cyl", (0.08, 0, 0.74), (0.08, 0, 0.88), 0.012, 8), ("cyl", (0.08, 0, 0.88), (0.17, 0, 0.88), 0.01, 8)]),
                  (mirror, [("box", 0.018, 0, 1.52, 0.008, 0.86, 0.72)]),                                      # wide RECTANGULAR mirror (P2 ref: not the round one; r14 review)
                  (frame, [("box", 0.012, 0, 1.52, 0.006, 0.9, 0.76)]), (led, [("box", 0.008, 0, 1.52, 0.004, 0.93, 0.79)])]     # a thin frame and a glowing LED halo behind it
        groups = groups + extras + [(chrome, _hv_drain)]
        return mesh_object(f"HomeVanityFactory({i}).spawn_asset({i})", groups, bevel=False)


class ShowerEnclosureFactory:
    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        tray = fl._flat("ir_shower_tray", (0.93, 0.93, 0.91), 0.25); glass = pa._flat("ir_shower_glass", (0.85, 0.92, 0.95), 0.03, transmission=0.95)
        chrome = fl._flat("ir_chrome", (0.8, 0.8, 0.82), 0.15, 1.0)
        S, H = 0.95, 2.1
        groups = [(tray, [("box", 0, 0, 0.04, S, S, 0.08)]),
                  (glass, [("box", S / 2 - 0.01, -0.1, 1.1, 0.012, S - 0.2, H - 0.2), ("box", 0.0, S / 2 - 0.01, 1.1, S, 0.012, H - 0.2)]),
                  (chrome, [("box", S / 2 - 0.01, -S / 2 + 0.02, 1.1, 0.03, 0.03, H - 0.2), ("box", S / 2 - 0.01, S / 2 - 0.02, 1.1, 0.03, 0.03, H - 0.2), ("box", S / 2 - 0.01, 0.1, 1.0, 0.04, 0.02, 0.5),
                            ("cyl", (-S / 2 + 0.05, 0.0, 2.0), (-S / 2 + 0.25, 0.0, 2.0), 0.012, 8), ("cyl", (-S / 2 + 0.25, 0.0, 2.0), (-S / 2 + 0.25, 0.0, 1.97), 0.07, 16),
                            ("cyl", (-S / 2 + 0.02, 0.3, 1.1), (-S / 2 + 0.08, 0.3, 1.1), 0.03, 12)])]
        bot = [fl._flat(f"ir_shower_bottle_{k}", c, 0.35) for k, c in enumerate(((0.9, 0.9, 0.88), (0.4, 0.55, 0.5), (0.85, 0.65, 0.4)))]
        groups += [(chrome, [("box", -S / 2 + 0.07, -0.2, 1.05, 0.1, 0.55, 0.012)])] + [(bot[k], [("cyl", (-S / 2 + 0.07, -0.38 + 0.15 * k, 1.056), (-S / 2 + 0.07, -0.38 + 0.15 * k, 1.056 + 0.13 + 0.03 * k), 0.025, 12)]) for k in range(3)]   # a shelf with three bottles (P2b r22: 'shower niche with toiletries')
        return mesh_object(f"ShowerEnclosureFactory({i}).spawn_asset({i})", groups, bevel=False)


class HomeKitchenRunFactory:
    """A home kitchen run along one wall (front +X, back at x = 0): 3.0-4.2 m of base cabinets (0.6 deep, 0.86 high, doors and drawers with bar handles) with a stone worktop, an inset sink with a
    gooseneck tap, a four-ring induction hob with an extractor hood over it, tiled splashback, wall cabinets (1.45-2.15 m) on both sides of the hood, and a tall fridge-freezer (0.7 x 0.7 x 1.85 m) at the left end.
    The whole run is one mesh. Kit keys: STYLE['kitchen_front'] ('white' | 'oak' | 'grey' | 'green'), default random."""
    FRONTS = {"white": (0.9, 0.9, 0.88), "oak": (0.62, 0.45, 0.28), "grey": (0.45, 0.47, 0.5), "green": (0.3, 0.42, 0.34), "steel": (0.7, 0.71, 0.73)}      # steel: a commercial kitchen (floors G / H: stainless runs, open steel shelves, a big hood)

    def __init__(self, seed):
        r = random.Random(seed); self.r = r; self.L = r.choice((3.0, 3.6, 4.2))
        self.front = pa.STYLE.get("kitchen_front") if pa.STYLE.get("kitchen_front") in self.FRONTS else r.choice(tuple(self.FRONTS))

    def spawn_asset(self, i):
        L = self.L
        steel_run = self.front == "steel"
        front = fl._flat(f"ir_kit_front_{self.front}", self.FRONTS[self.front], 0.3 if steel_run else 0.45, 1.0 if steel_run else 0.0, wood=self.front == "oak")
        body = fl._flat("ir_kit_body", (0.8, 0.8, 0.78), 0.5) if not steel_run else fl._flat("ir_kit_body_steel", (0.62, 0.63, 0.65), 0.35, 1.0); top = fl._flat("ir_kit_top", (0.93, 0.93, 0.91), 0.18) if not steel_run else fl._flat("ir_kit_front_steel_top", (0.74, 0.75, 0.77), 0.25, 1.0)
        steel = fl._flat("ir_kit_steel", (0.75, 0.75, 0.77), 0.25, 1.0); glass = fl._flat("ir_kit_hob", (0.03, 0.03, 0.035), 0.1, 0.5); tile = fl._flat("ir_kit_tile", (0.9, 0.9, 0.88), 0.2)
        fridge = fl._flat("ir_kit_fridge", (0.72, 0.73, 0.75), 0.3, 0.9)
        fw = 0.72 if not pa.STYLE.get('no_run_fridge') else (0.64 if pa.STYLE.get('oven_in_run') else 0.0)         # fridge width at the left end (y = -L/2 .. -L/2 + fw); kit no_run_fridge: a separate big_fridge is planned, one fridge only
        y0 = -L / 2 + fw + 0.02; run = L - fw - 0.02                    # the cabinet run
        n = max(3, int(round(run / 0.6))); cw = run / n
        base = [("box", 0.3, y0 + run / 2, 0.43, 0.6, run, 0.86)]
        fronts, handles, shelves = [], [], []
        for k in range(n):
            yc = y0 + (k + 0.5) * cw
            fronts.append(("box", 0.605, yc, 0.43, 0.018, cw - 0.012, 0.78))
            handles.append(("box", 0.625, yc + cw * 0.3, 0.7 if k % 3 == 1 else 0.5, 0.012, 0.012, 0.2))
        counter = [("box", 0.32, y0 + run / 2, 0.88, 0.66, run + 0.02, 0.035)]
        splash = [("box", 0.012, y0 + run / 2, 1.2, 0.02, run, 0.6)]
        sink_y = y0 + run * 0.28; hob_y = y0 + run * 0.7
        sink_cut = []                                                   # steel: a RECESSED three-basin sink (the worktop is cut open: dark deep basins, divider bars, a rim) instead of flat plates under the tap
        if steel_run:
            sa, sb = sink_y - 0.78, sink_y + 0.78
            counter = [("box", 0.32, (y0 + sa) / 2, 0.88, 0.66, sa - y0, 0.035), ("box", 0.32, (sb + y0 + run) / 2, 0.88, 0.66, y0 + run - sb, 0.035),
                       ("box", 0.06, sink_y, 0.88, 0.12, sb - sa, 0.035), ("box", 0.58, sink_y, 0.88, 0.14, sb - sa, 0.035)] + [("box", 0.32, sink_y + (k + 0.5) * 0.52 - 0.78 + 0.0, 0.88, 0.5, 0.05, 0.035) for k in (0, 1)]
            sink_cut = [("box", 0.32, sink_y + (k - 1) * 0.52, 0.66, 0.44, 0.42, 0.02) for k in (0, 1, 2)] + \
                       [("box", 0.32 + sx * 0.22, sink_y + (k - 1) * 0.52, 0.78, 0.015, 0.42, 0.22) for k in (0, 1, 2) for sx in (1, -1)] + \
                       [("box", 0.32, sink_y + (k - 1) * 0.52 + sy * 0.21, 0.78, 0.44, 0.015, 0.22) for k in (0, 1, 2) for sy in (1, -1)]
        if not steel_run:                                               # P2b r26 GEO-01 'the faucet sits over a solid countertop': a RECESSED single-bowl stainless sink (the worktop is cut open, walls and a floor 16 cm down), like the steel run's but one bowl
            sa, sb = sink_y - 0.3, sink_y + 0.3
            if y0 + 0.1 < sa and sb < y0 + run - 0.1:
                counter = [("box", 0.32, (y0 + sa) / 2, 0.88, 0.66, sa - y0, 0.035), ("box", 0.32, (sb + y0 + run) / 2, 0.88, 0.66, y0 + run - sb, 0.035),
                           ("box", 0.06, sink_y, 0.88, 0.12, sb - sa, 0.035), ("box", 0.58, sink_y, 0.88, 0.14, sb - sa, 0.035)]
                sink_cut = [("box", 0.32, sink_y, 0.72, 0.44, 0.58, 0.02)] + [("box", 0.32 + sx * 0.22, sink_y, 0.8, 0.015, 0.58, 0.16) for sx in (1, -1)] + \
                           [("box", 0.32, sink_y + sy * 0.29, 0.8, 0.44, 0.015, 0.16) for sy in (1, -1)] + [("cyl", (0.32, sink_y, 0.731), (0.32, sink_y, 0.735), 0.03, 12)]
        basin = [("box", 0.32, sink_y, 0.89, 0.42, 0.55, 0.012)] if (not steel_run and not sink_cut) else []       # steel: a deep THREE-basin wash sink (G/H refs)
        tap = [("cyl", (0.1, sink_y, 0.9), (0.1, sink_y, 1.12), 0.012, 8), ("cyl", (0.1, sink_y, 1.12), (0.22, sink_y, 1.12), 0.01, 8)]
        if steel_run:                                                   # a tall spring-neck spray tap over the middle basin
            tap = [("cyl", (0.08, sink_y, 0.9), (0.08, sink_y, 1.35), 0.014, 8), ("cyl", (0.08, sink_y, 1.35), (0.26, sink_y, 1.3), 0.01, 8)]
        hob = [("box", 0.32, hob_y, 0.9, 0.5, 0.6, 0.006)]
        hood = [("box", 0.22, hob_y, 1.95, 0.4, 0.6, 0.12), ("box", 0.14, hob_y, 2.2, 0.2, 0.22, 0.4)]
        if steel_run:                                                   # a canopy hood: wider, deeper, sloped by two stacked slabs, and a tall flue
            hood = [("box", 0.3, hob_y, 1.9, 0.62, 1.0, 0.14), ("box", 0.25, hob_y, 2.05, 0.45, 0.8, 0.16), ("box", 0.14, hob_y, 2.3, 0.28, 0.36, 0.4)]
        rings = [("cyl", (0.32 + dx, hob_y + dy, 0.9035), (0.32 + dx, hob_y + dy, 0.9055), rr, 20) for dx, dy, rr in ((-0.12, -0.15, 0.08), (-0.12, 0.15, 0.07), (0.12, -0.15, 0.07), (0.12, 0.15, 0.085))]
        if pa.STYLE.get("island_hob"):                                  # kit island_hob: the cooktop is on the ISLAND (P2b r10 ref), the rear run has no hob / hood
            hob, hood, rings = [], [], []
        wall = []
        for (a, b_) in ((y0 + 0.02, hob_y - 0.34), (hob_y + 0.34, y0 + run - 0.02)):
            if b_ - a > 0.35:
                if steel_run:                                           # open steel shelves with jars and pots instead of wall cabinets
                    shelves += [("box", 0.15, (a + b_) / 2, zz, 0.3, b_ - a, 0.025) for zz in (1.45, 1.85)]
                    shelves += [("box", 0.12, a + (b_ - a) * (k + 0.5) / 7, zz + 0.1, 0.1, 0.09, 0.17) for zz in (1.45, 1.85) for k in range(0, 7, 2)]          # jars
                    shelves += [("cyl", (0.14, a + (b_ - a) * (k + 0.5) / 7, zz + 0.035), (0.14, a + (b_ - a) * (k + 0.5) / 7, zz + 0.2), 0.065 if k % 3 else 0.085, 14) for zz in (1.45, 1.85) for k in range(1, 7, 2)]   # pots + pans: denser cookware (G r52)
                    shelves += [("box", 0.15, (a + b_) / 2, zz + 0.09, 0.26, (b_ - a) * 0.25, 0.012) for zz in (1.45, 1.85)] + [("cyl", (0.2, a + 0.1, 1.2), (0.2, b_ - 0.1, 1.2), 0.008, 6)]       # a stacked tray + a utensil rail
                else:
                    wall.append(("box", 0.18, (a + b_) / 2, 1.8, 0.36, b_ - a, 0.7)); 
        wfr = []
        for a, b_ in ((y0 + 0.02, hob_y - 0.34), (hob_y + 0.34, y0 + run - 0.02)):          # upper doors DIVIDED (~0.45 m each, a visible gap): P2b r6 'uppers read as undivided wood blocks'
            if b_ - a > 0.35 and not steel_run:
                nd = max(1, int(round((b_ - a) / 0.45))); dw = (b_ - a) / nd
                wfr += [("box", 0.365, a + (k + 0.5) * dw, 1.8, 0.016, dw - 0.02, 0.66) for k in range(nd)]
                handles += [("box", 0.38, a + (k + 0.5) * dw + (0.12 if k % 2 == 0 else -0.12), 1.5, 0.012, 0.012, 0.12) for k in range(nd)]
        fr = [("box", 0.35, -L / 2 + fw / 2, 0.925, 0.7, fw, 1.85), ("box", 0.7, -L / 2 + fw / 2, 1.3, 0.012, 0.012, 0.6), ("box", 0.7, -L / 2 + fw / 2, 0.55, 0.012, 0.012, 0.3)]
        if pa.STYLE.get('no_run_fridge'):
            fr = []
        if steel_run:
            try:                                                        # a white square-tile splashback (H kitchen ref: 'tiled backsplash'), world-space triplanar tile from tile_walls
                import bpy
                import tile_floor as _tf
                import tile_walls as _tw
                _png, _sz = _tf._bake((0.93, 0.93, 0.91), 0.15, 0.003, 0.03)
                tile = _tw._material(f"ir_wall_tile_{_png.stem}", bpy.data.images.load(str(_png), check_existing=True), _sz, 0.3)
            except Exception:                                           # noqa: BLE001 -- the plain splash stays
                pass
        groups = [(body, base + wall), (front, fronts + wfr), (steel, handles + tap + hood + fr[1:] + shelves + sink_cut), (top, counter), (tile, splash), (glass, basin + hob), (steel, rings), (fridge, fr[:1])]
        zt = 0.9; yl, yh = y0 + 0.12, y0 + run - 0.12                  # worktop things (P2b r22 CNT-03: 'worktops entirely bare'): a chopping board between sink and hob, three canisters, a fruit bowl
        okc = lambda y_: yl < y_ < yh
        board_m = fl._flat("ir_kit_board", (0.72, 0.55, 0.34), 0.5, wood=True); can_m = fl._flat("ir_kit_canister", (0.88, 0.86, 0.8), 0.35); bowl_m = fl._flat("ir_kit_bowl", (0.93, 0.93, 0.9), 0.25)
        fruit_m = fl._flat("ir_kit_fruit", (0.75, 0.3, 0.1), 0.5); herb_m = fl._flat("ir_kit_herb", (0.2, 0.4, 0.15), 0.7)
        yb = (sink_y + hob_y) / 2; yc = hob_y + 0.5; yf = sink_y - 0.5
        deco = []
        if okc(yb):
            deco.append((board_m, [("box", 0.38, yb, zt + 0.012, 0.3, 0.42, 0.024)]))
        if okc(yc):
            deco.append((can_m, [("cyl", (0.14, yc + dy, zt), (0.14, yc + dy, zt + hh), 0.05, 14) for dy, hh in ((-0.12, 0.18), (0.0, 0.22), (0.12, 0.15))]))
        if okc(yf):
            deco.append((bowl_m, [("cyl", (0.4, yf, zt), (0.4, yf, zt + 0.07), 0.13, 20)])); deco.append((fruit_m, [("sph", (0.4 + dx, yf + dy, zt + 0.1), 0.04, 1) for dx, dy in ((0.0, 0.0), (0.06, 0.05), (-0.05, 0.06))]))
        if okc(yc + 0.3):
            deco.append((herb_m, [("cyl", (0.16, yc + 0.3, zt), (0.16, yc + 0.3, zt + 0.12), 0.045, 12), ("sph", (0.16, yc + 0.3, zt + 0.17), 0.07, 1)]))
        if pa.STYLE.get('oven_in_run') and pa.STYLE.get('no_run_fridge') and not steel_run:      # kit oven_in_run (P2b kitchen: 'built-in oven + microwave stack' as the run's end bay): a tall unit at y = -L/2 .. -L/2 + 0.64
            oc = -L / 2 + 0.32; ob = fl._flat("ir_kit_oventower_body", tuple(HomeKitchenRunFactory.FRONTS.get(self.front, (0.9, 0.9, 0.88))), 0.45); osteel = fl._flat("ir_ot_steel", (0.72, 0.73, 0.75), 0.25, 1.0); og = fl._flat("ir_ot_glass", (0.03, 0.03, 0.035), 0.08)
            groups += [(ob, [("box", 0.31, oc, 1.05, 0.62, 0.62, 2.1), ("box", 0.626, oc, 0.3, 0.012, 0.6, 0.5), ("box", 0.626, oc, 1.95, 0.012, 0.6, 0.3)]),
                       (osteel, [("box", 0.632, oc, 1.0, 0.02, 0.6, 0.55), ("box", 0.645, oc, 1.27, 0.012, 0.4, 0.012), ("box", 0.632, oc, 1.6, 0.02, 0.6, 0.4), ("box", 0.64, oc + 0.22, 1.7, 0.006, 0.07, 0.3)]),
                       (og, [("box", 0.644, oc, 0.98, 0.006, 0.46, 0.4), ("box", 0.644, oc - 0.04, 1.6, 0.006, 0.4, 0.3)])]
        groups += [] if steel_run else deco                              # steel (commercial) kitchens keep their own stocking: floors G / H are frozen/tuned
        return mesh_object(f"HomeKitchenRunFactory({i}).spawn_asset({i})", groups, bevel=False)


class BalconyTableFactory:
    """A round white balcony table (user ref varanda_01): 1.1 m round white top (4 cm), single slim chrome pedestal with a round foot, 0.74 m high; origin at the centre on the floor."""

    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        if os.environ.get("ROOM_TERRACE_SET") == "1":                       # P2b r36: a fluted cream pedestal + a round white-veined marble top (ref balcony_0-0__0)
            marble = fl._flat("ir_bal_marble", (0.9, 0.88, 0.84), 0.15); cream = fl._flat("ir_bal_flute", (0.88, 0.84, 0.74), 0.55)
            flutes = [("cyl", (0.17 * math.cos(k * math.pi / 8), 0.17 * math.sin(k * math.pi / 8), 0.0), (0.17 * math.cos(k * math.pi / 8), 0.17 * math.sin(k * math.pi / 8), 0.68), 0.032, 8) for k in range(16)]
            parts = [(marble, [("cyl", (0, 0, 0.68), (0, 0, 0.74), 0.5, 40)]), (cream, flutes + [("cyl", (0, 0, 0.0), (0, 0, 0.67), 0.15, 24), ("cyl", (0, 0, 0.0), (0, 0, 0.04), 0.27, 28), ("cyl", (0, 0, 0.64), (0, 0, 0.68), 0.26, 28)])]
            return mesh_object(f"BalconyTableFactory({i}).spawn_asset({i})", parts, bevel=False)
        top = fl._flat("ir_bal_top", (0.93, 0.93, 0.91), 0.3); steel = fl._flat("ir_bal_steel", (0.75, 0.76, 0.78), 0.25, 1.0)
        wh = fl._flat("ir_bal_cup", (0.95, 0.95, 0.93), 0.2); bread = fl._flat("ir_bal_pastry", (0.72, 0.5, 0.25), 0.7); stem = fl._flat("ir_bal_stem", (0.2, 0.4, 0.15), 0.7)
        bloom = fl._flat("ir_bal_bloom", (0.85, 0.35, 0.4), 0.6); coffee = fl._flat("ir_bal_coffee", (0.12, 0.07, 0.04), 0.3)
        z = 0.74; cups, cof = [], []
        for a_ in (0.8, 2.4):                                                   # two cups on saucers (P2b r22 CNT-01: a bare table)
            x, y = 0.3 * math.cos(a_), 0.3 * math.sin(a_)
            cups += [("cyl", (x, y, z), (x, y, z + 0.008), 0.065, 16), ("cyl", (x, y, z + 0.008), (x, y, z + 0.07), 0.04, 14)]; cof += [("cyl", (x, y, z + 0.066), (x, y, z + 0.069), 0.036, 14)]
        pot = [("cyl", (-0.05, -0.15, z), (-0.05, -0.15, z + 0.13), 0.07, 16), ("cyl", (0.0, -0.15, z + 0.08), (0.1, -0.15, z + 0.11), 0.012, 6), ("cyl", (-0.05, -0.15, z + 0.13), (-0.05, -0.15, z + 0.15), 0.03, 12)]
        plate = [("cyl", (-0.2, 0.15, z), (-0.2, 0.15, z + 0.012), 0.11, 20)]; past = [("cyl", (-0.2 + dx, 0.15 + dy, z + 0.012), (-0.2 + dx, 0.15 + dy, z + 0.04), 0.035, 10) for dx, dy in ((0.03, 0.0), (-0.03, 0.04), (-0.02, -0.04))]
        vase = [("cyl", (0.02, 0.0, z), (0.02, 0.0, z + 0.14), 0.04, 12)]
        stems = [("cyl", (0.02, 0.0, z + 0.14), (0.02 + dx, dy, z + 0.28), 0.004, 5) for dx, dy in ((0.04, 0.02), (-0.03, 0.03), (0.0, -0.04))]
        blooms = [("sph", (0.02 + dx, dy, z + 0.29), 0.022, 1) for dx, dy in ((0.04, 0.02), (-0.03, 0.03), (0.0, -0.04))]
        return mesh_object(f"BalconyTableFactory({i}).spawn_asset({i})", [(top, [("cyl", (0, 0, 0.70), (0, 0, 0.74), 0.55, 28)]),
                                                                   (steel, [("cyl", (0, 0, 0.0), (0, 0, 0.70), 0.035, 10), ("cyl", (0, 0, 0.0), (0, 0, 0.02), 0.3, 24)]),
                                                                   (wh, cups + pot + plate + vase), (coffee, cof), (bread, past), (stem, stems), (bloom, blooms)], bevel=False)


class BalconyChairFactory:
    """A teal upholstered dining chair for the balcony (ref varanda_01): 0.5 x 0.5 x 0.85 m, rounded teal seat + curved back (a box back with a rounded top slab), four slim oak legs; front +X, origin at the centre."""
    TEAL = (0.07, 0.38, 0.42)

    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        if os.environ.get("ROOM_TERRACE_SET") == "1":                       # a dark-teal TUB chair (a rounded shell: seat + a wraparound back and arms) on four splayed walnut legs
            c = (0.04, 0.2, 0.22); teal = fl._flat("ir_bal_tub", (c[0] * (0.9 + 0.2 * self.r.random()), c[1], c[2]), 0.8); wal = fl._flat("ir_bal_walnut", (0.28, 0.16, 0.09), 0.5, wood=True)
            shell = [("rbox", (0.0, 0, 0.46), (0.52, 0.52, 0.11), (0, 0, 0)), ("rbox", (-0.2, 0, 0.7), (0.1, 0.54, 0.42), (0, -0.12, 0))] + \
                    [("rbox", (-0.02, sy * 0.25, 0.62), (0.4, 0.07, 0.3), (0, 0, 0)) for sy in (1, -1)] + [("rbox", (-0.12, sy * 0.2, 0.62), (0.18, 0.1, 0.3), (0, 0, sy * 0.4)) for sy in (1, -1)]
            legs = [("cyl", (sx * 0.17, sy * 0.17, 0.2), (0.017, 0.011, 0.42), (sy * 0.1, -sx * 0.1, 0)) for sx in (1, -1) for sy in (1, -1)]
            return pa._prims(f"BalconyChairFactory({i}).spawn_asset({i})", [(teal, shell), (wal, legs)])
        t = self.TEAL; teal = fl._flat("ir_bal_teal", (t[0] * (0.9 + 0.2 * self.r.random()), t[1], t[2]), 0.75); oak = fl._flat("ir_bal_oak", (0.62, 0.45, 0.28), 0.5, wood=True)
        seat = [("rbox", (0.0, 0.0, 0.45), (0.5, 0.5, 0.1), (0, 0, 0))]
        back = [("rbox", (-0.22, 0.0, 0.68), (0.1, 0.48, 0.42), (0, -0.14, 0))] + [("rbox", (-0.1, sy * 0.25, 0.6), (0.34, 0.07, 0.3), (0, 0, 0.0)) for sy in (1, -1)]      # soft rounded cushions with wraparound arms (P2b r13)
        legs = [("cyl", (sx * 0.2, sy * 0.2, 0.21), (0.016, 0.012, 0.42), (0, 0, 0)) for sx in (1, -1) for sy in (1, -1)]
        return pa._prims(f"BalconyChairFactory({i}).spawn_asset({i})", [(teal, seat + back), (oak, legs)])


class SingleBedFactory:
    """A single bed with a cream upholstered headboard (P2 suite 2 ref: two of them side by side, teal blankets folded at the foot): 2.05 x 0.95 x 1.05 m, HEAD at x = 0 (against the wall), foot toward +X.
    Oak base, white sheet, one pillow, a folded teal blanket over the foot of the mattress."""

    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        oak = fl._flat("ir_sbed_oak", (0.62, 0.45, 0.28), 0.5, wood=True); cream = fl._flat("ir_sbed_cream", (0.9, 0.86, 0.78), 0.8); sheet = fl._flat("ir_sbed_sheet", (0.93, 0.93, 0.9), 0.85)
        t = (0.07, 0.38, 0.42); teal = fl._flat("ir_sbed_teal", (t[0] * (0.9 + 0.2 * self.r.random()), t[1], t[2]), 0.8)
        L, W = 2.05, 0.95
        R0 = (0, 0, 0)
        base = [("rbox", (L / 2 + 0.02, 0, 0.16), (L - 0.04, W, 0.16), R0)]
        mattress = [("rbox", (L / 2 + 0.03, 0, 0.43), (L - 0.08, W - 0.06, 0.28), R0)]
        head = [("rbox", (0.05, 0, 0.58), (0.1, W, 0.95), R0)]
        pillow = [("rbox", (0.3, 0, 0.62), (0.45, 0.62, 0.13), (0, -0.1, 0))]
        blanket = [("rbox", (L - 0.38, 0, 0.58), (0.5, W - 0.02, 0.06), R0), ("rbox", (L - 0.12, 0, 0.5), (0.05, W - 0.02, 0.2), R0)]      # folded blanket draped over the foot
        return pa._prims(f"SingleBedFactory({i}).spawn_asset({i})", [(oak, base), (cream, head), (sheet, mattress + pillow), (teal, blanket)])

class FoldedLinenStackFactory:
    """Folded towels / blankets for treatment couches (F3 r25 GEO-01: the old stack was rigid sharp blocks). 2-4 soft layers: rounded boxes 0.32 x 0.44 x 0.06 m with a slight turn per layer, two alternating tones and a
    thin darker fold edge on each. The OBJECT NAME stays TowelStackFactory (realize / catalog logic keys on it)."""

    def __init__(self, seed):
        r = random.Random(seed); self.r = r; self.n = r.randint(2, 4)
        self.c = r.choice(((0.92, 0.92, 0.9), (0.6, 0.75, 0.85), (0.75, 0.82, 0.78), (0.9, 0.85, 0.75)))

    def spawn_asset(self, i):
        r = self.r; a = fl._flat(f"ir_linen_a_{int(self.c[0] * 100)}_{int(self.c[2] * 100)}", self.c, 0.95); b = fl._flat(f"ir_linen_b_{int(self.c[0] * 100)}", tuple(v * 0.9 for v in self.c), 0.95)
        parts_a, parts_b = [], []
        for k in range(self.n):
            z = 0.03 + k * 0.058; yaw = r.uniform(-0.09, 0.09); dx = r.uniform(-0.008, 0.008); dy = r.uniform(-0.008, 0.008)
            (parts_a if k % 2 == 0 else parts_b).append(("rbox", (dx, dy, z), (0.32, 0.44, 0.058), (0, 0, yaw)))
            parts_b.append(("rbox", (dx + 0.153, dy, z), (0.012, 0.42, 0.04), (0, 0, yaw)))                  # the fold edge
        return pa._prims(f"TowelStackFactory({i}).spawn_asset({i})", [(a, parts_a), (b, parts_b)])


class UpholsteredBenchFactory:
    """Beam seating with shaped, upholstered seats (F3 r25 AST-01: the moulded seats read as rigid square slabs): 3-5 seats on a steel beam, each a rounded seat cushion with a slight dish tilt and a rounded back cushion
    leaning back. Front +X. The OBJECT NAME stays WaitingBenchFactory (the clinic-lobby bench cap and wall logic key on it); colour = one per room, like the moulded one."""

    def __init__(self, seed):
        r = random.Random(seed); self.n = r.choice((3, 4, 4, 5))
        if pa.VENUE == "pharmacy" and pa.STYLE.get("accent_rgb"):
            self.c = tuple(pa.STYLE.get("band_rgb") or (0.4, 0.6, 0.22))
        else:
            self.c = pa._ROOM_PICK.setdefault("waiting_bench", r.choice(((0.15, 0.35, 0.55), (0.12, 0.12, 0.13), (0.2, 0.4, 0.42), (0.55, 0.25, 0.15))))

    def spawn_asset(self, i):
        n, w = self.n, 0.56; L = n * w
        fab = pa._flat(f"ir_ubench_{int(self.c[0] * 100)}_{int(self.c[2] * 100)}", self.c, 0.8); steel = pa._flat("ir_desk_frame", (0.75, 0.75, 0.76), 0.35, 0.8)
        seats = [("rbox", (0.0, -L / 2 + (k + 0.5) * w, 0.46), (0.48, w - 0.05, 0.09), (0.0, 0.03, 0.0)) for k in range(n)]
        backs = [("rbox", (-0.2, -L / 2 + (k + 0.5) * w, 0.72), (0.09, w - 0.07, 0.38), (0.0, -0.16, 0.0)) for k in range(n)]
        frame = [("box", (-0.05, 0, 0.4), (0.06, L, 0.05), (0, 0, 0))] + [("box", (-0.05, sy * (L / 2 - 0.15), 0.2), (0.05, 0.05, 0.4), (0, 0, 0)) for sy in (1, -1)]
        return pa._prims(f"WaitingBenchFactory({i}).spawn_asset({i})", [(fab, seats + backs), (steel, frame)])


# ---- P2 reference gaps (user 2026-10-20 review r17): laundry run, kitchen island, big fridge, fitted wardrobe, curtains, towel rail, media wall -----------------------------------------------------------
_OAK = (0.62, 0.45, 0.28)


class LaundryRunFactory:
    """The laundry / service area run (ref aserv_01), back at x = 0, front +X: 2.8 m of pale base cabinets under a long pale worktop; a deep utility sink tank at the left end, a washing machine and a dryer
    (white, round glass doors) under the worktop, upper cabinets (white with oak accent) along the wall, a drying rail with folded towels. 0.62 x 2.8 x 2.2 m."""

    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        white = fl._flat("ir_lr_white", (0.92, 0.92, 0.9), 0.35); top = fl._flat("ir_lr_top", (0.86, 0.84, 0.8), 0.2); oak = fl._flat("ir_lr_oak", _OAK, 0.5, wood=True)
        steel = fl._flat("ir_lr_steel", (0.75, 0.76, 0.78), 0.25, 1.0); glass = fl._flat("ir_lr_glass", (0.15, 0.2, 0.25), 0.05); tow = fl._flat("ir_lr_towel", (0.6, 0.75, 0.85), 0.95)
        L = 2.8; D = 0.62
        base = [("box", D / 2, 0, 0.42, D, L, 0.84)]
        worktop = [("box", D / 2 + 0.01, 0, 0.87, D + 0.02, L, 0.04)]
        tank = [("box", D / 2, -L / 2 + 0.38, 0.9, 0.45, 0.6, 0.12)]                                         # the sink tank basin sits on the top at the left end
        wm = [("box", D + 0.005, -0.1, 0.42, 0.01, 0.6, 0.8), ("box", D + 0.005, 0.65, 0.42, 0.01, 0.6, 0.8)]       # washer front + a cabinet door beside it (ONE washer: P2b r13 'two circular-door appliances')
        ring_ = [("cyl", (D + 0.012, y, 0.4), (D + 0.034, y, 0.4), 0.255, 28) for y in (-0.1,)]                  # a chrome door ring (porthole)
        doors = [("cyl", (D + 0.03, y, 0.4), (D + 0.038, y, 0.4), 0.205, 24) for y in (-0.1,)]                  # the dark glass inside the ring
        doors += [("sph", (D - 0.125, -0.1, 0.4), 0.205, 2)]                                                    # a bulging glass dome (P2b r22 GEO-01: 'a flat disc for the door'): the cap of a sphere sunk into the front
        panel_ = [("box", D + 0.012, y, 0.76, 0.012, 0.5, 0.07) for y in (-0.1,)] + [("cyl", (D + 0.018, y + 0.17, 0.76), (D + 0.034, y + 0.17, 0.76), 0.022, 12) for y in (-0.1,)] + [("box", D + 0.014, 0.65, 0.5, 0.012, 0.012, 0.3)]   # control panel + dial on the washer; a handle on the cabinet door   # control panel + dial
        uppers = [("box", 0.16, y, 1.72, 0.32, 0.7, 0.9) for y in (-0.95, -0.25, 0.45, 1.15)]
        accent = [("box", 0.325, -0.25, 1.72, 0.01, 0.66, 0.86), ("box", 0.325, 1.15, 1.72, 0.01, 0.66, 0.86)]
        rail = [("cyl", (0.2, -L / 2 + 0.1, 1.25), (0.2, -L / 2 + 0.1 + 0.9, 1.25), 0.012, 8)] + [("cyl", (0.45, -L / 2 + 0.2, 2.05), (0.45, L / 2 - 0.2, 2.05), 0.012, 8)] + \
               [("cyl", (0.45, y, 2.05), (0.45, y, 2.2), 0.008, 6) for y in (-L / 2 + 0.2, L / 2 - 0.2)]                    # a ceiling-hung drying rail (P2b r6: 'drying rack with garments')
        towels = [("box", 0.2, -L / 2 + 0.3 + 0.26 * k, 1.1, 0.03, 0.2, 0.28) for k in range(3)]
        garments = []                                                                  # drying-rail garments: shoulders + body, hangers turned ~45 deg
        for k in range(12):
            yy = -L / 2 + 0.3 + 0.2 * k; ln = 0.5 - 0.05 * (k % 3); yw = 0.6 + 0.1 * (k % 3)
            garments += [("tap", 0.45, yy, 2.0 - 0.02 - (ln - 0.04) / 2, ln - 0.04, 0.12, 0.17 + 0.02 * (k % 3), 0.04 / 0.34, yw), ("tap", 0.45, yy, 2.0, 0.04, 0.09, 0.12, 0.04 / 0.24, yw)]       # tapered shirts on the rail (P2b r26 GEO-01 'rigid rectangular slabs')
        return mesh_object(f"LaundryRunFactory({i}).spawn_asset({i})", [(white, base + uppers + wm), (top, worktop), (steel, tank + rail + ring_ + panel_), (glass, doors), (oak, accent), (tow, towels + garments)], bevel=False)


class KitchenIslandFactory:
    """A compact kitchen island with an induction hob (ref cozinha_01): 1.8 x 0.9 x 0.95 m, front +X: cream base with oak end panel, pale stone worktop with a 0.3 m breakfast overhang on the back, a dark 4-ring hob inset,
    two pendant-free bar stools are separate items."""

    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        cream = fl._flat("ir_isl_cream", (0.9, 0.87, 0.8), 0.45); oak = fl._flat("ir_isl_oak", _OAK, 0.5, wood=True); stone = fl._flat("ir_isl_stone", (0.9, 0.9, 0.88), 0.15); dark = fl._flat("ir_isl_hob", (0.03, 0.03, 0.035), 0.1)
        L, D = 1.8, 0.9
        base = [("box", 0.35, 0, 0.43, 0.7, L - 0.04, 0.86)]
        ends = [("box", 0.35, sy * (L / 2 - 0.02), 0.43, 0.7, 0.04, 0.86) for sy in (1, -1)]
        topp = [("box", 0.45, 0, 0.9, D, L, 0.05)]
        hob = [("box", 0.36, 0, 0.926, 0.5, 0.58, 0.004)]
        rings = [("cyl", (0.28 + 0.16 * a, -0.15 + 0.3 * b, 0.929), (0.28 + 0.16 * a, -0.15 + 0.3 * b, 0.931), 0.07, 18) for a in (0, 1) for b in (0, 1)]
        return mesh_object(f"KitchenIslandFactory({i}).spawn_asset({i})", [(cream, base), (oak, ends), (stone, topp)] + ([(dark, hob + rings)] if pa.STYLE.get("island_hob") else []), bevel=True)      # no hob (P2b r3: 'a second cooktop was added'): the cooking is on the rear run; the island is the prep surface + breakfast ledge


class BigFridgeFactory:
    """A tall double-door fridge-freezer (ref cozinha_01): 0.9 x 0.75 x 1.85 m, front +X, stainless doors with two vertical handles, a dark gap line."""

    def __init__(self, seed=0):
        self.seed = seed

    def spawn_asset(self, i):
        steel = fl._flat("ir_bf_steel", (0.62, 0.63, 0.65), 0.3, 1.0); dark = fl._flat("ir_bf_dark", (0.05, 0.05, 0.055), 0.5)
        W, D, H = 0.9, 0.75, 1.85
        body = [("box", D / 2, 0, H / 2, D, W, H)]
        gap = [("box", D + 0.002, 0, H / 2, 0.004, 0.01, H - 0.1), ("box", D + 0.002, 0, 0.72, 0.004, W - 0.06, 0.01)]
        handles = [("box", D + 0.03, sy * 0.06, 1.2, 0.03, 0.025, 0.7) for sy in (1, -1)]
        return mesh_object(f"BigFridgeFactory({i}).spawn_asset({i})", [(steel, body + handles), (dark, gap)], bevel=True)


class OakWardrobeFactory:
    """A fitted warm-oak wardrobe wall (refs suite2 / suite3): 2.4 x 0.6 x 2.4 m, back at x = 0: six full-height oak doors with fine vertical grooves, slim dark pull bars, a plinth and a top fascia."""

    def __init__(self, seed):
        self.r = random.Random(seed); self.L = self.LEN or self.r.choice((2.4, 2.4, 3.0))

    LEN = None                                                    # layout size_m[0] (set by RoomRealizer around the spawn): a 0.8 m wardrobe in a hotel entry, not the 2.4 m wall

    def spawn_asset(self, i):
        oak = fl._flat("ir_wd_oak", _OAK, 0.45, wood=True); oak2 = fl._flat("ir_wd_oak2", (0.56, 0.4, 0.24), 0.45, wood=True); dark = fl._flat("ir_wd_pull", (0.06, 0.06, 0.06), 0.4)
        L, D, H = self.L, 0.6, 2.4; n = int(round(L / 0.4))
        carcase = [("box", D / 2, 0, H / 2, D, L, H)]
        doors = [("box", D + 0.01, -L / 2 + (k + 0.5) * L / n, H / 2 + 0.04, 0.02, L / n - 0.012, H - 0.12) for k in range(0, n, 2)]
        doors2 = [("box", D + 0.01, -L / 2 + (k + 0.5) * L / n, H / 2 + 0.04, 0.02, L / n - 0.012, H - 0.12) for k in range(1, n, 2)]
        pulls = [("box", D + 0.03, -L / 2 + (k + 0.5) * L / n + 0.12, 1.1, 0.02, 0.015, 0.4) for k in range(0, n, 2)]
        return mesh_object(f"OakWardrobeFactory({i}).spawn_asset({i})", [(oak, carcase + doors), (oak2, doors2), (dark, pulls)], bevel=False)


class CurtainFactory:
    """A pair of floor-length pleated cream curtains on a ceiling track (suite / living refs): 2.4 x 0.12 x 2.6 m, back at x = 0 (the wall side), front +X: 18 slim pleat boxes per half with a slight depth wave, a dark track."""

    def __init__(self, seed):
        self.r = random.Random(seed); t = self.r.choice(((0.9, 0.87, 0.8), (0.86, 0.85, 0.82), (0.8, 0.84, 0.82))); self.c = t
        if self.FORCE_RGB:                                        # big_glass drapes (BIGGLASS_CURTAIN_RGB), set by RoomRealizer._bigglass_curtains
            self.c = tuple(self.FORCE_RGB)

    FORCE_RGB = None

    def spawn_asset(self, i):
        r = self.r; fab = fl._flat(f"ir_cur_{int(self.c[0] * 100)}_{int(self.c[2] * 100)}", self.c, 0.9); track = fl._flat("ir_cur_track", (0.2, 0.2, 0.2), 0.5, 0.6)
        W, H = 2.4, 2.6; n = 14; gw = 0.55                       # drawn open: each half is gathered into a 0.55 m bunch at its end of the track (P2b r2: closed pleats hid the glazing)
        parts = []
        for half in (-1, 1):
            for k in range(n):
                y = half * (W / 2 - gw + (k + 0.5) * gw / n)
                parts.append(("box", 0.05 + 0.04 * (k % 2), y, H / 2, 0.035, gw / n * 0.95, H - 0.06))
        sheer = fl._flat("ir_cur_sheer", (0.97, 0.96, 0.93), 0.9); sb = sheer.node_tree.nodes["Principled BSDF"]; sb.inputs["Alpha"].default_value = float(pa.STYLE.get("sheer_alpha") or 0.12)      # a SHEER layer across the whole width behind the drapes (P2b refs: 'broad sheer curtains')
        sh = [("box", 0.03, 0, H / 2, 0.006, W - 0.06, H - 0.1)]
        return mesh_object(f"CurtainFactory({i}).spawn_asset({i})", [(fab, parts), (track, [("box", 0.04, 0, H - 0.015, 0.05, W, 0.03)]), (sheer, sh)], bevel=False)


class TowelRailFactory:
    """A wall towel rail with two folded hanging towels (bathroom refs): 0.1 x 0.7 x 0.55 m, back at x = 0; mount at ~1.1 m (WALL_MOUNTED)."""

    def __init__(self, seed):
        self.r = random.Random(seed); self.c = self.r.choice(((0.12, 0.45, 0.5), (0.92, 0.92, 0.9), (0.6, 0.75, 0.85)))

    def spawn_asset(self, i):
        steel = fl._flat("ir_tr_steel", (0.8, 0.8, 0.82), 0.2, 1.0); tow = fl._flat(f"ir_tr_tow_{int(self.c[0] * 100)}", self.c, 0.95)
        rail = [("cyl", (0.06, -0.35, 0.5), (0.06, 0.35, 0.5), 0.011, 8), ("cyl", (0.0, -0.33, 0.5), (0.06, -0.33, 0.5), 0.01, 6), ("cyl", (0.0, 0.33, 0.5), (0.06, 0.33, 0.5), 0.01, 6)]
        towels = [("box", 0.075, -0.15 + 0.3 * k, 0.28, 0.03, 0.26, 0.46) for k in range(2)]
        return mesh_object(f"TowelRailFactory({i}).spawn_asset({i})", [(steel, rail), (tow, towels)], bevel=False)


class MediaWallFactory:
    """A living-room media wall (ref estar_01: 'blank dark TV panel along the left wall'): 3.2 x 0.4 x 2.4 m, back at x = 0: an oak-veneer / stone panel wall with a recessed dark TV panel (1.6 m), warm LED strips at the
    edges, a low floating oak cabinet beneath."""

    W = 5.4

    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        panel = fl._flat("ir_mw_panel", (0.78, 0.74, 0.66), 0.5); oak = fl._flat("ir_mw_oak", _OAK, 0.45, wood=True); tvm = fl._flat("ir_mw_tv_screen", (0.02, 0.02, 0.025), 0.08)
        led = fl._flat("ir_mw_led", (1.0, 0.8, 0.5), 0.3); lb = led.node_tree.nodes["Principled BSDF"]; lb.inputs["Emission Color"].default_value = (1.0, 0.78, 0.45, 1); lb.inputs["Emission Strength"].default_value = 4.0
        W, H = self.W, 2.4
        back = [("box", 0.03, 0, H / 2, 0.06, W, H)]
        tvp = [("box", 0.07, 0, 1.35, 0.03, min(1.6, W * 0.55), 0.92)]
        cab = [("box", 0.2, 0, 0.45, 0.4, W - 1.0, 0.4)]
        strips = [("box", 0.065, sy * min(1.6, W * 0.55) / 2 * 1.1, 1.35, 0.01, 0.02, 1.0) for sy in (1, -1)] + [("box", 0.065, 0, 0.62, 0.01, W - 1.0, 0.015)]
        return mesh_object(f"MediaWallFactory({i}).spawn_asset({i})", [(panel, back), (tvm, tvp), (oak, cab), (led, strips)], bevel=False)


class SteelPrepTableFactory:
    """A stainless prep island (floor G/H kitchen refs): 1.8 x 0.9 x 0.92 m: a brushed steel top with a back-edge upstand, four square steel legs, a lower shelf with a stack of trays, two steel mixing bowls and white tubs,
    a wooden chopping board on top."""

    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        steel = fl._flat("ir_pt_steel", (0.7, 0.71, 0.72), 0.28, 1.0); wood = fl._flat("ir_pt_board", (0.72, 0.55, 0.34), 0.5, wood=True); tub = fl._flat("ir_pt_tub", (0.92, 0.92, 0.9), 0.4)
        L, D = 1.8, 0.9
        top = [("box", 0, 0, 0.9, D, L, 0.04)]
        legs = [("box", sx * (D / 2 - 0.04), sy * (L / 2 - 0.04), 0.44, 0.045, 0.045, 0.88) for sx in (1, -1) for sy in (1, -1)]
        shelf = [("box", 0, 0, 0.22, D - 0.1, L - 0.1, 0.025)]
        trays = [("box", 0.0, -0.45, 0.25 + 0.02 * k, 0.5, 0.55, 0.015) for k in range(6)]
        bowls = [("cyl", (0.0, 0.2, 0.235), (0.0, 0.2, 0.31), 0.17, 18), ("cyl", (0.0, 0.62, 0.235), (0.0, 0.62, 0.3), 0.15, 18)]
        tubs = [("box", 0.0, 0.0, 0.29, 0.32, 0.36, 0.14), ("box", 0.0, 0.0, 0.43, 0.32, 0.36, 0.14)]
        board = [("box", 0.0, -0.3, 0.935, 0.45, 0.6, 0.03)]
        return mesh_object(f"SteelPrepTableFactory({i}).spawn_asset({i})", [(steel, top + legs + shelf + trays + bowls), (tub, tubs), (wood, board)], bevel=True)


def _basin(cx, cy, zc, A, B, H, wall=0.035):
    """A vessel basin with a real bowl (P2b r22 GEO-01: 'solid slab, no bowl'): four rim walls round a hollow, a floor 6 cm below the rim and a chrome drain disc. -> (white prims, drain prims). zc/H: the old solid block's centre / height."""
    zt, zb = zc + H / 2, zc - H / 2 + 0.02
    rim = [("box", cx + sx * (A / 2 - wall / 2), cy, (zt + zb) / 2, wall, B, zt - zb) for sx in (1, -1)] + [("box", cx, cy + sy * (B / 2 - wall / 2), (zt + zb) / 2, A - 2 * wall, wall, zt - zb) for sy in (1, -1)]
    floor_ = [("box", cx, cy, zt - 0.06 - 0.01, A - 2 * wall + 0.01, B - 2 * wall + 0.01, 0.02)]
    return rim + floor_, [("cyl", (cx + 0.02, cy, zt - 0.069), (cx + 0.02, cy, zt - 0.064), 0.022, 14)]


class OakBasinVanityFactory:
    """A pale-oak vanity cabinet on slim legs with a white vessel basin, chrome tap and a ROUND brass-framed mirror (floors G / H restroom refs): 0.5 x 1.3 m, cabinet 0.85 m high, mirror 0.9 m across at 1.55 m;
    back at x = 0, front +X. The mirror belongs to the object (wall piece), 2.1 m high overall."""

    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        oak = fl._flat("ir_ov_oak", (0.72, 0.55, 0.34), 0.45, wood=True); white = fl._flat("ir_ov_white", (0.94, 0.94, 0.92), 0.12); chrome = fl._flat("ir_ov_chrome", (0.8, 0.8, 0.82), 0.12, 1.0)
        brass = fl._flat("ir_ov_brass", (0.78, 0.6, 0.25), 0.25, 1.0); mir = fl._flat("ir_ov_mirror", (0.8, 0.85, 0.88), 0.03, 1.0)
        L, D = 1.3, 0.5
        glow_parts = []
        body = [("box", D / 2, 0, 0.5, D - 0.02, L - 0.04, 0.6), ("box", D / 2, 0, 0.82, D, L, 0.04)]
        legs = [("box", sx * (D / 2 - 0.06) + D / 2, sy * (L / 2 - 0.06), 0.1, 0.04, 0.04, 0.2) for sx in (1, -1) for sy in (1, -1)] if not pa.STYLE.get("vanity_floating") else []   # kit vanity_floating: a wall-hung cabinet (H refs)
        doors = [("box", D - 0.005, sy * (L / 4), 0.5, 0.012, L / 2 - 0.04, 0.56) for sy in (1, -1)]
        pulls = [("box", D + 0.01, sy * 0.04 + sy * 0.0, 0.62, 0.01, 0.01, 0.12) for sy in (1, -1)]
        basin, drain = _basin(D / 2 + 0.02, 0, 0.91, 0.38, 0.55, 0.1)
        tap = [("cyl", (0.1, 0, 0.9), (0.1, 0, 1.08), 0.012, 8), ("cyl", (0.1, 0, 1.08), (0.22, 0, 1.08), 0.01, 8)]
        ring = [("cyl", (0.02, 0, 1.55), (0.04, 0, 1.55), 0.46, 40)]
        if pa.STYLE.get("vanity_sconces"):                                # kit: brass globe sconces either side of the mirror (H restroom ref)
            for sy in (1, -1):
                ring += [("cyl", (0.03, sy * 0.66, 1.5), (0.07, sy * 0.66, 1.5), 0.012, 8)]
                glow_parts.extend([("cyl", (0.09, sy * 0.66, 1.5), (0.12, sy * 0.66, 1.5), 0.075, 20), ("cyl", (0.12, sy * 0.66, 1.5), (0.14, sy * 0.66, 1.5), 0.05, 20)])
        glass = [("cyl", (0.04, 0, 1.55), (0.05, 0, 1.55), 0.43, 40)]
        return mesh_object(f"OakBasinVanityFactory({i}).spawn_asset({i})", [(oak, body + legs + doors), (chrome, pulls + tap + drain), (white, basin), (brass, ring), (mir, glass)] + ([(fl._flat("ir_ov_globe", (1.0, 0.95, 0.85), 0.3), glow_parts)] if glow_parts else []), bevel=False)


class TiledWcCubicleFactory:
    """A white-tiled WC cubicle with an AJAR oak door (floors G / H restroom refs): 1.4 x 1.2 m (2.0 m with the door ajar), 2.0 m high; back at x = 0 (the room wall), front +X: two tiled side partitions with oak edge strips, an oak door leaf
    opened 50 deg at the front hinge, a close-coupled white WC (tank + bowl + lid), a toilet-roll holder."""

    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        import math as _m
        tile = fl._flat("ir_wcc_tile", tuple(pa.STYLE.get("cubicle_rgb") or (0.92, 0.92, 0.9)), 0.3); oak = fl._flat("ir_wcc_oak", (0.72, 0.55, 0.34), 0.45, wood=True) if not pa.STYLE.get("cubicle_door_rgb") else fl._flat("ir_wcc_door_%d" % int(sum(pa.STYLE["cubicle_door_rgb"]) * 100), tuple(pa.STYLE["cubicle_door_rgb"]), 0.4)   # kit cubicle_door_rgb: a plain painted door + edge strips (M market: white, not oak)
        wc = fl._flat("ir_wcc_wc", (0.95, 0.95, 0.94), 0.1)
        black = fl._flat("ir_wcc_handle", (0.04, 0.04, 0.045), 0.4, 1.0)
        W, D, H = 1.2, 1.4, 2.0
        R0 = (0, 0, 0)
        side = [("box", (D / 2, sy * (W / 2), H / 2), (D, 0.06, H), R0) for sy in (1, -1)]
        edge = [("box", (D, sy * (W / 2), H / 2), (0.05, 0.075, H), R0) for sy in (1, -1)]
        th = _m.radians(50); hy = -W / 2 + 0.04; lw = 0.75
        door = [("box", (D + (lw / 2) * _m.sin(th), hy + (lw / 2) * _m.cos(th), 1.0), (0.04, lw, 1.95), (0, 0, -th))]
        handle = [("box", (D + (lw * 0.9) * _m.sin(th) + 0.03, hy + (lw * 0.9) * _m.cos(th), 1.0), (0.03, 0.03, 0.14), (0, 0, -th))]
        wcp = [("rbox", (0.14, 0, 0.62), (0.22, 0.4, 0.42), R0),                       # the cistern
               ("rbox", (0.43, 0, 0.27), (0.56, 0.38, 0.32), R0),                      # a conventional rounded-rectangle bowl (H r66: 'bulbous' ellipsoid → plain cistern WC)
               ("cyl", (0.4, 0, 0.1), (0.15, 0.11, 0.2), R0),                          # the pedestal
               ("sph", (0.44, 0, 0.485), (0.235, 0.185, 0.03), R0),                      # the lid / seat: an oval, not a slab (G r52)
               ("cyl", (0.07, 0.45, 0.8), (0.06, 0.06, 0.12), (0, 1.5708, 0))]         # a toilet roll
        return pa._prims(f"TiledWcCubicleFactory({i}).spawn_asset({i})", [(tile, side), (oak, edge + door), (wc, wcp), (black, handle)])


class WaterHeaterFactory:
    """A cylindrical hot-water tank (floors G / H utility refs): 0.55 m round, 1.5 m high, white enamel jacket with a dark cap, two chrome pipes with a valve on top, a small thermostat dial, a drain at the foot;
    back at x = 0 (against the wall), front +X."""

    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        white = fl._flat("ir_wh_white", (0.92, 0.92, 0.9), 0.3); cap = fl._flat("ir_wh_cap", (0.25, 0.26, 0.28), 0.4); chrome = fl._flat("ir_wh_pipe", (0.75, 0.76, 0.78), 0.2, 1.0)
        cx = 0.28
        body = [("cyl", (cx, 0, 0.12), (cx, 0, 1.45), 0.26, 28)]
        base = [("cyl", (cx, 0, 0.0), (cx, 0, 0.12), 0.22, 20), ("cyl", (cx, 0, 1.45), (cx, 0, 1.52), 0.24, 24)]
        pipes = [("cyl", (cx - 0.1, 0.0, 1.5), (cx - 0.1, 0.0, 1.85), 0.018, 10), ("cyl", (cx + 0.1, 0.0, 1.5), (cx + 0.1, 0.0, 1.7), 0.018, 10),
                 ("cyl", (cx - 0.1, 0.0, 1.85), (0.02, 0.0, 1.85), 0.018, 10), ("cyl", (cx + 0.1, 0.0, 1.7), (0.02, 0.0, 1.7), 0.018, 10), ("box", cx - 0.1, 0.0, 1.7, 0.06, 0.06, 0.06)]
        dial = [("cyl", (cx + 0.26, 0, 0.9), (cx + 0.29, 0, 0.9), 0.04, 14)]
        return mesh_object(f"WaterHeaterFactory({i}).spawn_asset({i})", [(white, body), (cap, base + dial), (chrome, pipes)], bevel=False)


class MopSinkFactory:
    """A stainless mop sink (floors G / H utility refs): a 0.6 x 0.5 steel service basin 0.25 m deep on a steel frame, a steel splash panel, a tall gooseneck tap with hose spray at 1.0 m, and a mop + a broom hung on a rail
    beside it; back at x = 0, front +X; 0.5 x 1.3 x 1.5 m."""

    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        steel = fl._flat("ir_ms_steel", (0.72, 0.73, 0.75), 0.25, 1.0); wood = fl._flat("ir_ms_handle", (0.7, 0.55, 0.35), 0.5, wood=True); head = fl._flat("ir_ms_head", (0.88, 0.88, 0.84), 0.9)
        basin = [("box", 0.28, -0.3, 0.45, 0.5, 0.6, 0.05), ("box", 0.28, -0.3, 0.22, 0.5, 0.6, 0.03)]
        walls = [("box", 0.28, -0.3 + sy * 0.29, 0.34, 0.5, 0.02, 0.25) for sy in (1, -1)] + [("box", 0.53, -0.3, 0.34, 0.02, 0.6, 0.25), ("box", 0.04, -0.3, 0.34, 0.02, 0.6, 0.25)]
        frame = [("box", 0.28 + sx * 0.22, -0.3 + sy * 0.26, 0.14, 0.04, 0.04, 0.28) for sx in (1, -1) for sy in (1, -1)]
        splash = [("box", 0.02, -0.3, 0.75, 0.02, 0.62, 0.5)]
        tap = [("cyl", (0.06, -0.3, 0.5), (0.06, -0.3, 1.1), 0.016, 10), ("cyl", (0.06, -0.3, 1.1), (0.22, -0.3, 1.1), 0.014, 10), ("cyl", (0.22, -0.3, 1.1), (0.22, -0.3, 1.0), 0.014, 10)]
        rail = [("cyl", (0.05, 0.1, 1.35), (0.05, 0.6, 1.35), 0.012, 8)]
        mop = [("cyl", (0.07, 0.25, 1.35), (0.07, 0.25, 0.3), 0.012, 8), ("cyl", (0.07, 0.25, 0.3), (0.07, 0.25, 0.1), 0.06, 12)]
        broom = [("cyl", (0.07, 0.45, 1.35), (0.07, 0.45, 0.2), 0.011, 8)]
        return mesh_object(f"MopSinkFactory({i}).spawn_asset({i})", [(steel, basin + walls + frame + splash + tap + rail), (wood, broom), (head, mop)], bevel=False)


class FicusPlantFactory:
    """A potted ficus / rubber-plant for offices (B r16: Infinigen's LargePlantContainer rendered 'rigid flat jagged blades, angular forked sprigs' in all six offices): a cream stone pot, three slim woody stems and a crown of ~90
    SMOOTH oval leaves (flattened ellipsoids, two greens, each tilted outward and down) in a 0.7 m wide, 0.9 m tall rounded mass; 1.45 m overall, 0.5 m footprint. Origin on the floor at the pot centre."""

    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        import math as _m
        r = self.r
        pot = fl._flat("ir_fic_pot", (0.86, 0.84, 0.78), 0.75); soil = fl._flat("ir_fic_soil", (0.1, 0.07, 0.05), 0.95); wood = fl._flat("ir_fic_stem", (0.35, 0.25, 0.16), 0.7)
        g1 = fl._flat("ir_fic_leaf_a", (0.07, 0.3, 0.09), 0.45); g2 = fl._flat("ir_fic_leaf_b", (0.13, 0.4, 0.12), 0.4)
        potp = [("cyl", (0, 0, 0.19), (0.2, 0.26, 0.38), (0, 0, 0))]
        soilp = [("cyl", (0, 0, 0.375), (0.19, 0.19, 0.02), (0, 0, 0))]
        stems = []
        for k in range(3):
            a = k * 2.1 + r.uniform(0, 0.5); tx, ty = 0.1 * _m.cos(a), 0.1 * _m.sin(a)
            stems.append(("cyl", (tx / 2, ty / 2, 0.8), (0.014, 0.01, 0.85), (-ty * 0.5, tx * 0.5, 0)))
        la, lb = [], []
        for k in range(90):
            a = r.uniform(0, 2 * _m.pi); h = r.uniform(0.5, 1.4); rad = 0.34 * _m.sqrt(max(0.0, 1.0 - ((h - 0.95) / 0.5) ** 2)) * r.uniform(0.7, 1.0)
            x, y, z = rad * _m.cos(a), rad * _m.sin(a), h
            phi = r.uniform(0.6, 1.25)                           # the leaf's long axis leans outward by phi from vertical
            leaf = ("sph", (x, y, z), (0.05, 0.016, 0.1), (0.0, phi, a + r.uniform(-0.3, 0.3)))
            (la if k % 2 == 0 else lb).append(leaf)
        o = pa._prims(f"FicusPlantFactory({i}).spawn_asset({i})", [(pot, potp), (soil, soilp), (wood, stems), (g1, la), (g2, lb)])
        sc_ = float(pa.STYLE.get("ficus_scale") or 1.0)                   # kit ficus_scale: taller naturalistic floor trees (H: 1.4 -> ~2 m)
        if sc_ != 1.0:
            from mathutils import Matrix
            o.data.transform(Matrix.Scale(sc_, 4)); o.data.update()
        return o


class OakCredenzaFactory:
    """A long LOW oak sideboard (B refs: 'long low oak side cabinets' instead of a tall bookcase): 1.8 x 0.4 x 0.75 m (length alternatives 1.4 / 2.2), two rows of flush oak doors with slim recessed pulls, a 3 cm top with a slight
    overhang, on a 6 cm plinth. Back at x = 0, front +X."""

    def __init__(self, seed):
        self.r = random.Random(seed); self.L = self.r.choice((1.4, 1.8, 2.2))

    def spawn_asset(self, i):
        oak = fl._flat("ir_cred_oak", (0.72, 0.55, 0.34), 0.45, wood=True); oak2 = fl._flat("ir_cred_oak2", (0.66, 0.5, 0.3), 0.45, wood=True); dark = fl._flat("ir_cred_pull", (0.05, 0.05, 0.05), 0.5)
        L, D, H = self.L, 0.4, 0.75
        n = max(3, int(round(L / 0.5))); w = (L - 0.04) / n
        body = [("box", D / 2, 0, 0.06 + (H - 0.09) / 2, D - 0.02, L - 0.02, H - 0.09), ("box", D / 2 + 0.01, 0, H - 0.015, D + 0.02, L + 0.02, 0.03)]
        doors = [("box", D - 0.005, -L / 2 + 0.02 + (k + 0.5) * w, 0.06 + (H - 0.09) / 2, 0.015, w - 0.01, H - 0.11) for k in range(0, n, 2)]
        doors2 = [("box", D - 0.005, -L / 2 + 0.02 + (k + 0.5) * w, 0.06 + (H - 0.09) / 2, 0.015, w - 0.01, H - 0.11) for k in range(1, n, 2)]
        pulls = [("box", D + 0.008, -L / 2 + 0.02 + (k + 0.5) * w, H - 0.12, 0.012, 0.1, 0.012) for k in range(n)]
        plinth = [("box", D / 2 - 0.02, 0, 0.03, D - 0.06, L - 0.06, 0.06)]
        return mesh_object(f"OakCredenzaFactory({i}).spawn_asset({i})", [(oak, body + doors), (oak2, doors2), (dark, pulls + plinth)], bevel=False)


class StoneDiningTableFactory:
    """A long pale-stone dining table (P2b ref estar_02 / plan: 'a white marble table, eight chairs'): 2.4 x 1.0 m, 5 cm top in pale warm marble with a soft drift, two broad stone-coloured slab legs set in from the ends; 0.76 m high.
    Origin at the footprint centre on the floor, length along local y (like TableDiningFactory)."""

    def __init__(self, seed):
        self.r = random.Random(seed); self.L = self.r.choice((2.2, 2.4, 2.6))

    def spawn_asset(self, i):
        stone = fl._flat("ir_sdt_stone", (0.9, 0.88, 0.84), 0.12); leg = fl._flat("ir_sdt_leg", (0.82, 0.8, 0.76), 0.2)
        L, W = self.L, 1.0
        return mesh_object(f"StoneDiningTableFactory({i}).spawn_asset({i})", [(stone, [("box", 0, 0, 0.735, W, L, 0.05)]),
                                                                          (leg, [("box", 0, sy * (L / 2 - 0.45), 0.355, 0.5, 0.1, 0.71) for sy in (1, -1)])], bevel=True)


class WhiteDiningChairFactory:
    """A white upholstered dining chair with slim oak legs (P2b ref: 'white upholstered chairs'): 0.5 x 0.55 m, seat 0.46 m, back to 0.88 m, soft rounded cushions; front +X."""

    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        _uc = tuple(pa.STYLE.get("upholstery_srgb") or (0.93, 0.92, 0.89)); fab = fl._flat(f"ir_wdc_fabric_{int(_uc[0] * 100)}_{int(_uc[1] * 100)}", _uc, 0.85); oak = fl._flat("ir_wdc_oak", (0.72, 0.55, 0.34), 0.45, wood=True)
        legs = [("cyl", (sx * 0.2, sy * 0.2, 0.22), (0.016, 0.012, 0.44), (0, 0, 0)) for sx in (1, -1) for sy in (1, -1)]
        seat = [("rbox", (0, 0, 0.44), (0.46, 0.46, 0.1), (0, 0, 0))]
        back = [("rbox", (-0.21, 0, 0.7), (0.09, 0.44, 0.42), (0, -0.12, 0))]
        return pa._prims(f"WhiteDiningChairFactory({i}).spawn_asset({i})", [(oak, legs), (fab, seat + back)])


import math as _mm
math_cos, math_sin = _mm.cos, _mm.sin


class OpenWardrobeFactory:
    """An OPEN walk-in closet wall (P2b closet ref: 'open rails with hanging garments, lit shelves', ours were closed louvred cupboards): 2.4 x 0.55 x 2.3 m, back at x = 0: oak back panel and uprights, a shelf bay
    (four shelves with folded knits) on one side, two hanging rails (1.8 m and 1.05 m) with ~40 garments in neutral colours on the rest, a warm LED strip under the top. Front +X."""

    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        r = self.r
        oak = fl._flat("ir_ow_oak", (0.7, 0.53, 0.33), 0.45, wood=True); rail = fl._flat("ir_ow_rail", (0.78, 0.78, 0.8), 0.25, 1.0)
        led = fl._flat("ir_ow_led", (1.0, 0.8, 0.5), 0.3); b = led.node_tree.nodes["Principled BSDF"]; b.inputs["Emission Color"].default_value = (1.0, 0.78, 0.45, 1); b.inputs["Emission Strength"].default_value = 4.0
        pal = [fl._flat(f"ir_ow_g{k}", c, 0.9) for k, c in enumerate(((0.92, 0.9, 0.86), (0.75, 0.68, 0.58), (0.55, 0.55, 0.56), (0.15, 0.2, 0.32), (0.3, 0.3, 0.3), (0.85, 0.8, 0.7), (0.12, 0.35, 0.38)))]
        L, D, H = 2.4, 0.55, 2.3
        frame = [("box", 0.01, 0, H / 2, 0.02, L, H)] + [("box", D / 2, sy * (L / 2 - 0.015), H / 2, D, 0.03, H) for sy in (1, -1)] + [("box", D / 2, 0, H - 0.015, D, L, 0.03)]
        mid = L / 2 - 0.9                                                  # the shelf bay occupies y in [mid, L/2]
        frame += [("box", D / 2, mid, H / 2, D, 0.03, H)] + [("box", D / 2 - 0.02, (mid + L / 2) / 2, z, D - 0.04, L / 2 - mid - 0.03, 0.025) for z in (0.45, 0.9, 1.35, 1.8)]
        rails = [("cyl", (0.28, -L / 2 + 0.02, z), (0.28, mid - 0.02, z), 0.014, 8) for z in (1.8, 1.05)]
        strip = [("box", D - 0.06, 0, H - 0.04, 0.02, L - 0.1, 0.012)]
        groups = [[] for _ in pal]
        hang = []                                                          # hanger bars + hooks (steel)
        for z, ln0 in ((1.8, 0.95), (1.05, 0.85)):                         # long garments on the top rail, short ones on the lower; each: hook, hanger bar, SHOULDERS, a body that flares to the hem
            y = -L / 2 + 0.07
            while y < mid - 0.07:
                k = r.randrange(len(pal)); w = r.uniform(0.03, 0.055); ln = ln0 * r.uniform(0.7, 1.1); yw = r.uniform(0.55, 0.95); xo = 0.28 + r.uniform(-0.015, 0.015)      # hangers turned ~45 deg: broad garment faces show to the front, not edge-on slats
                yc = y + w / 2
                hang.append(("cyl", (xo, yc, z + 0.035), (xo, yc, z + 0.075), 0.003, 5))
                hang.append(("box", xo, yc, z - 0.01, 0.4, 0.006, 0.01, yw))
                g = groups[k]
                zt = z - 0.05                                              # P2b r23 AST-02 'rigid rectangular strips, stepped': a smoothly tapering flattened frustum body (narrow shoulders -> flared hem), a short neck block, tapered sleeves
                g.append(("tap", xo, yc, zt - (ln - 0.05) / 2, ln - 0.05, 0.14, 0.2 + r.uniform(0.0, 0.05), w / 0.4, yw))
                g.append(("tap", xo, yc, zt + 0.0, 0.05, 0.12, 0.16, (w * 0.8) / 0.3, yw))
                if r.random() < 0.6:                                       # sleeves hanging at the sides, slightly splayed
                    for sx in (-1, 1):
                        sxc = xo + sx * 0.17 * math_cos(yw); syc = yc + sx * 0.17 * math_sin(yw)
                        g.append(("tap", sxc, syc, z - 0.2, 0.3, 0.035, 0.05, 1.0, yw))
                y += r.uniform(0.07, 0.11)
        for z in (0.45, 0.9, 1.35, 1.8):                                   # folded knits on the shelves
            y = (mid + 0.08)
            while y < L / 2 - 0.2:
                k = r.randrange(len(pal)); groups[k].append(("box", 0.28, y + 0.14, z + 0.07, 0.36, 0.28, r.uniform(0.1, 0.18))); y += 0.3
        mats = [(oak, frame), (rail, rails + hang), (led, strip)] + [(pal[k], g) for k, g in enumerate(groups) if g]
        return mesh_object(f"OpenWardrobeFactory({i}).spawn_asset({i})", mats, bevel=False)


class SectionalSofaFactory:
    """A large L-shaped corner sectional in warm light grey (P2b living ref: 'large corner sectional'): 3.2 m main run x 1.0 deep + a 1.9 m chaise return, 0.85 m high, loose back + arm cushions, pale oak plinth feet, a few
    pillows (cream + teal). Front +X (the seat faces +X); the return extends toward +X at the +y end; origin at the main run's back centre... footprint ~3.2 x 1.9."""

    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        fab = fl._flat("ir_sec_fabric", (0.66, 0.65, 0.62), 0.9); cush = fl._flat("ir_sec_cushion", (0.72, 0.71, 0.68), 0.9); oak = fl._flat("ir_sec_feet", (0.7, 0.53, 0.33), 0.45, wood=True)
        cream = fl._flat("ir_sec_pillow_c", (0.93, 0.9, 0.84), 0.9); teal = fl._flat("ir_sec_pillow_t", (0.1, 0.4, 0.43), 0.9)
        L, D, R = 3.2, 1.0, 1.9
        rb = lambda c, sz, rot=(0, 0, 0): ("rbox", c, sz, rot)
        base = [rb((D / 2, 0, 0.27), (D, L, 0.3)), rb((D / 2 + (R - D) / 2, L / 2 - 0.5, 0.27), (R, 1.0, 0.3))]
        # The long back already covers the chaise end. A second contained
        # block produces coincident front faces in that region.
        back = [rb((0.14, 0, 0.62), (0.26, L, 0.52))]
        arms = [rb((D / 2, -L / 2 + 0.12, 0.55), (D, 0.24, 0.42)), rb((R - 0.12, L / 2 - 0.5, 0.55), (0.24, 1.0, 0.42))]
        seats = [rb((0.55, -L / 2 + 0.25 + (k + 0.5) * (L - 0.5 - 1.0) / 3, 0.5), (0.78, (L - 0.5 - 1.0) / 3 - 0.03, 0.16)) for k in range(3)] + [rb((0.55 + (R - D) / 2 + 0.2, L / 2 - 0.5, 0.5), (0.78 + (R - D), 0.96, 0.16))]
        feet = [("box", (sx, sy, 0.06), (0.06, 0.06, 0.12), (0, 0, 0)) for sx in (0.08, R - 0.08) for sy in (-L / 2 + 0.08, L / 2 - 0.08)]
        pill = [rb((0.3, -0.8, 0.75), (0.14, 0.46, 0.4), (0, 0.15, 0.25))]
        pill2 = [rb((0.3, 0.2, 0.75), (0.14, 0.46, 0.4), (0, 0.15, -0.2))]
        return pa._prims(f"SectionalSofaFactory({i}).spawn_asset({i})", [(fab, base + back + arms), (cush, seats), (oak, feet), (cream, pill), (teal, pill2)])


class BedroomMediaFactory(MediaWallFactory):
    """A bedroom TV wall (P2b master suite ref: 'TV + a long floating console'): the media wall at 2.4 m wide, 2.4 m high."""
    W = 2.4


class SoftBedFactory:
    """A king bed in the P2b suite refs ('soft white quilt + teal throw, upholstered foot bench', ours: dark mixed angular bedding): 2.1 x 1.9 m, head at x = 0 (against the wall), foot toward +X; a broad cream channelled
    headboard 1.1 m high, low oak platform, white mattress, a soft white quilt with a rolled edge, a teal throw band across the foot, 4 white pillows + 2 teal cushions."""

    throw_rgb = None                                                                          # set by realize from kit bed_throw_by_room

    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        r = self.r
        oak = fl._flat("ir_sfb_oak", (0.62, 0.45, 0.28), 0.5, wood=True); cream = fl._flat("ir_sfb_cream", (0.88, 0.84, 0.76), 0.85); white = fl._flat("ir_sfb_white_b", (0.90, 0.88, 0.84), 0.9)
        teal = fl._flat("ir_sfb_petrol", (0.06, 0.17, 0.19), 0.9)                                   # muted petrol knit (refs ~0.06,0.17,0.19 linear), not aqua
        taupe = fl._flat("ir_sfb_taupe", (0.45, 0.38, 0.30), 0.9); oat = fl._flat("ir_sfb_oat", (0.70, 0.65, 0.57), 0.92); greige = fl._flat("ir_sfb_greige", (0.62, 0.57, 0.50), 0.9)
        tr = getattr(self, "throw_rgb", None)                                                           # kit: master = fringed taupe throw instead of teal
        if tr:
            teal_t = fl._flat("ir_sfb_throw_%d_%d" % (int(tr[0] * 100), int(tr[2] * 100)), tuple(tr), 0.9)
        else:
            teal_t = teal
        L, W = 2.1, float(pa.STYLE.get("bed_width_m") or 1.9)                                        # kit bed_width_m: a queen / double instead of the 1.9 m king (hotel: the plan's 1.8 m bed and its nightstands)
        HW = W + (0.1 if pa.STYLE.get('bed_width_m') else 0.3)                                       # headboard: 5 cm past the mattress each side when the kit sets a bed width (hotel nightstands sit right beside it)
        R0 = (0, 0, 0)
        base = [("rbox", (L / 2 + 0.02, 0, 0.14), (L - 0.04, W + 0.08, 0.2), R0)]
        head = [("rbox", (0.06, 0, 0.62), (0.14, HW, 1.05), R0)] + [("rbox", (0.14, (k - 3.5) * HW / 8, 0.62), (0.05, HW / 8 - 0.03, 0.95), R0) for k in range(8)]
        mattress = [("rbox", (L / 2 + 0.08, 0, 0.4), (L - 0.1, W - 0.04, 0.3), R0)]
        quilt = [("rbox", (L / 2 + 0.34, 0, 0.58), (L - 0.62, W + 0.06, 0.1), R0), ("rbox", (L - 0.28, 0, 0.55), (0.18, W + 0.1, 0.16), R0)]
        throw = [("rbox", (L - 0.55, 0, 0.635), (0.45, W + 0.06, 0.05), R0), ("rbox", (L - 0.32, 0, 0.5), (0.05, W + 0.06, 0.3), R0)] + \
                [("rbox", (L - 0.55, sy * (W / 2 + 0.04), 0.52), (0.45, 0.05, 0.22), R0) for sy in (1, -1)]          # the throw DRAPES over the foot and both sides
        pill = [("rbox", (0.32, (k - 1.5) * (W - 0.5) / 3, 0.7), (0.2, 0.46, 0.5), (0, -0.3, 0.1 * (1 - 2 * (k % 2)))) for k in range(4)]
        cush = [("rbox", (0.55, sy * 0.35, 0.74), (0.14, 0.4, 0.3), (0, -0.3, 0.3 * sy)) for sy in (1, -1)]
        coverlet = [("rbox", (L / 2 + 0.5, 0, 0.625), (L - 0.95, W + 0.1, 0.04), R0)]                   # oatmeal coverlet folded over the quilt, under the throw
        return pa._prims(f"SoftBedFactory({i}).spawn_asset({i})", [(oak, base), (cream, head), (white, mattress + quilt + pill[:2]), (greige, pill[2:]), (oat, coverlet), (teal_t, throw), (teal, cush)])

class BedBenchFactory:
    """An upholstered bench for the foot of a bed (P2b suite refs): 1.5 x 0.45 x 0.46 m, cream seat with a soft top, slim oak legs; front +X."""

    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        fab = fl._flat("ir_bb_fabric", (0.88, 0.84, 0.76), 0.88); oak = fl._flat("ir_bb_oak", (0.62, 0.45, 0.28), 0.5, wood=True)
        seat = [("box", 0, 0, 0.38, 0.45, 1.5, 0.12)]
        legs = [("cyl", (sx * 0.17, sy * 0.66, 0.0), (sx * 0.17, sy * 0.66, 0.32), 0.022, 8) for sx in (1, -1) for sy in (1, -1)]
        return mesh_object(f"BedBenchFactory({i}).spawn_asset({i})", [(fab, seat), (oak, legs)], bevel=True)


class StoneCoffeeTableFactory:
    """A low pale rounded stone coffee table (P2b living ref): 1.1 x 0.7 m, 0.38 m high, a thick softly rounded pale travertine top on a wide recessed plinth."""

    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        stone = fl._flat("ir_sct_stone", (0.86, 0.82, 0.74), 0.25); plinth = fl._flat("ir_sct_plinth", (0.8, 0.76, 0.68), 0.35)
        top = [("cyl", (0, 0, 0.3), (0, 0, 0.38), 0.4, 28)]
        return mesh_object(f"StoneCoffeeTableFactory({i}).spawn_asset({i})", [(stone, [("box", 0, 0, 0.33, 0.7, 1.1, 0.1)]), (plinth, [("box", 0, 0, 0.14, 0.5, 0.9, 0.28)])], bevel=True)


class LongOakVanityFactory:
    """ONE long shared oak vanity with two vessel basins and a continuous rectangular mirror with a concealed LED edge (B / P2b master bath refs: 'one continuous double-basin counter + continuous mirror wall'):
    2.6 x 0.5 m, floating-height cabinet (legless, 0.2 m off the floor), two basins at +-0.65 m, two chrome taps, a 2.4 x 0.95 m mirror at 1.15-2.1 m with a warm LED strip behind its lower edge. Back at x = 0, front +X."""

    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        oak = fl._flat("ir_lov_oak", (0.72, 0.55, 0.34), 0.45, wood=True) if not pa.STYLE.get("vanity_rgb") else fl._flat("ir_lov_body_%d" % int(sum(pa.STYLE["vanity_rgb"]) * 100), tuple(pa.STYLE["vanity_rgb"]), 0.35)    # kit vanity_rgb: a painted / laminate cabinet instead of oak
        white = fl._flat("ir_lov_white", (0.94, 0.94, 0.92), 0.12); chrome = fl._flat("ir_lov_chrome", (0.8, 0.8, 0.82), 0.12, 1.0)
        mir = fl._flat("ir_lov_mirror", (0.8, 0.85, 0.88), 0.03, 1.0); led = fl._flat("ir_lov_led", (1.0, 0.85, 0.6), 0.3)
        b = led.node_tree.nodes["Principled BSDF"]; b.inputs["Emission Color"].default_value = (1.0, 0.82, 0.55, 1); b.inputs["Emission Strength"].default_value = 5.0
        L, D = 2.6, 0.5
        body = [("box", D / 2, 0, 0.5, D - 0.02, L - 0.04, 0.6), ("box", D / 2, 0, 0.82, D, L, 0.04)]
        doors = [("box", D - 0.005, -L / 2 + (k + 0.5) * L / 4, 0.5, 0.012, L / 4 - 0.04, 0.56) for k in range(4)]
        basins, drains = [], []
        for sy in (1, -1):
            b_, d_ = _basin(D / 2 + 0.02, sy * 0.65, 0.91, 0.38, 0.55, 0.1); basins += b_; drains += d_
        taps = [e for sy in (1, -1) for e in (("cyl", (0.1, sy * 0.65, 0.9), (0.1, sy * 0.65, 1.08), 0.012, 8), ("cyl", (0.1, sy * 0.65, 1.08), (0.22, sy * 0.65, 1.08), 0.01, 8))]
        mirror = [("box", 0.025, 0, 1.63, 0.02, 2.4, 0.95)]
        strip = [("box", 0.03, 0, 1.12, 0.012, 2.4, 0.02)]
        return mesh_object(f"LongOakVanityFactory({i}).spawn_asset({i})", [(oak, body + doors), (white, basins), (chrome, taps + drains), (mir, mirror), (led, strip)], bevel=False)


class LinearPendantFactory:
    """A long LINEAR pendant for the dining table (P2b ref: 'a long linear pendant'): a 1.5 m slim bar (6 x 4 cm, matte black casing with a warm emissive underside strip) on two thin cords; origin at the ceiling point, hangs `drop` m."""

    def __init__(self, seed=0, drop=0.8):
        self.drop = drop

    def spawn_asset(self, i):
        black = fl._flat("ir_lp_black", (0.03, 0.03, 0.03), 0.4); glow = fl._flat("ir_lp_glow", (1.0, 0.85, 0.6), 0.3)
        b = glow.node_tree.nodes["Principled BSDF"]; b.inputs["Emission Color"].default_value = (1.0, 0.8, 0.5, 1); b.inputs["Emission Strength"].default_value = 3.0
        d, L = self.drop, 1.5
        cords = [("cyl", (0, sy * (L / 2 - 0.1), -d), (0, sy * (L / 2 - 0.1), 0), 0.003, 6) for sy in (1, -1)]      # P2b r31: the cord started at -d/2, so the lower half down to the bar was missing
        bar = [("box", 0, 0, -d, 0.06, L, 0.04)]
        strip = [("box", 0, 0, -d - 0.022, 0.04, L - 0.06, 0.006)]
        return mesh_object(f"LinearPendantFactory({i}).spawn_asset({i})", [(black, cords + bar), (glow, strip)], bevel=False)


class RecessedSpotFactory:
    """A flush recessed ceiling downlight (G / H kitchen refs: 'recessed lighting', ours: a faceted white ABO pendant): a 0.14 m white trim ring with a warm emissive disc; origin at the ceiling plane, hangs 1 cm."""

    def __init__(self, seed=0):
        pass

    def spawn_asset(self, i):
        trim = fl._flat("ir_rs_trim", (0.92, 0.92, 0.9), 0.4); glow = fl._flat("ir_rs_glow", (1.0, 0.9, 0.7), 0.3)
        b = glow.node_tree.nodes["Principled BSDF"]; b.inputs["Emission Color"].default_value = (1.0, 0.88, 0.65, 1); b.inputs["Emission Strength"].default_value = 6.0
        return mesh_object(f"RecessedSpotFactory({i}).spawn_asset({i})", [(trim, [("cyl", (0, 0, -0.006), (0, 0, 0.0), 0.075, 20)]), (glow, [("cyl", (0, 0, -0.012), (0, 0, -0.006), 0.055, 20)])], bevel=False)


class SmallFicusFactory(FicusPlantFactory):
    """The table / shelf size of the ficus (kit plant_style=ficus replaces ABO's PLANTER, whose single-stem jagged broad leaves showed in every B office): 0.3 x the full plant, ~0.45 m tall."""

    def spawn_asset(self, i):
        from mathutils import Matrix
        o = super().spawn_asset(i)
        o.data.transform(Matrix.Scale(0.3, 4))                      # scale the mesh itself (an object scale is easy to lose in footprint / copy code)
        o.data.update()
        return o


class AtriumPlanterFactory:
    """ONE long raised planter with white-stone ground cover and dense tall palms (O2 atrium ref): 3.4 x 0.9 x 0.5 m, pale stone-clad sides, a bed of white pebbles, six palms (slim trunks 1.3-1.9 m, a fan of 14 drooping fronds each),
    a few low ferns; back at x = 0, front +X; ~2.4 m tall."""

    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        import math as _m
        r = self.r
        _sc = tuple(float(v) for v in os.environ["ROOM_ATRIUM_STONE_RGB"].split(",")) if os.environ.get("ROOM_ATRIUM_STONE_RGB") else (0.88, 0.86, 0.8)         # e.g. 0.5,0.5,0.52: a grey stone planter
        stone = fl._flat("ir_ap_stone", _sc, 0.35); peb = fl._flat("ir_ap_pebble", (0.7, 0.67, 0.62) if os.environ.get("ROOM_ATRIUM_STONE_RGB") else (0.93, 0.92, 0.88), 0.7); trunk = fl._flat("ir_ap_trunk", (0.38, 0.28, 0.18), 0.8)
        g1 = fl._flat("ir_ap_frond_a", (0.08, 0.32, 0.1), 0.45); g2 = fl._flat("ir_ap_frond_b", (0.14, 0.42, 0.12), 0.4)
        L, D, H = 3.4, 0.9, 0.5
        box = [("box", (D / 2, 0, H / 2), (D, L, H), (0, 0, 0))]
        top = [("box", (D / 2, 0, H + 0.006), (D - 0.08, L - 0.08, 0.014), (0, 0, 0))]
        trunks, fa, fb = [], [], []
        n = 0 if pa.STYLE.get("planter_palms") == "none" else 6               # kit planter_palms=none: only the bed + pebbles; the plants are Infinigen's (user rule 2026-10-21), placed by the planner
        for k in range(n):
            y = -L / 2 + 0.35 + k * (L - 0.7) / max(n - 1, 1); x = D / 2 + r.uniform(-0.12, 0.12); h = r.uniform(1.0, 1.5)
            trunks.append(("cyl", (x, y, H + h / 2), (0.04, 0.03, h), (0.0, 0.0, 0.0)))
            for f in range(26):                                                       # a full crown: broad drooping fronds
                a = f * 2 * _m.pi / 26 + r.uniform(-0.15, 0.15); phi = r.uniform(1.0, 1.55); ln = r.uniform(0.75, 1.05)
                cx, cy, cz = x + _m.cos(a) * _m.sin(phi) * ln * 0.5, y + _m.sin(a) * _m.sin(phi) * ln * 0.5, H + h + 0.1 - _m.cos(phi) * ln * 0.3 - _m.sin(phi) * ln * 0.12
                (fa if f % 2 == 0 else fb).append(("sph", (cx, cy, cz), (0.03, 0.075, ln / 2), (0.0, phi, a)))
            for f in range(10):                                                       # low ferns round the base
                a = f * 2 * _m.pi / 10 + r.uniform(-0.2, 0.2); ln = r.uniform(0.35, 0.5)
                fa.append(("sph", (x + _m.cos(a) * 0.2, y + _m.sin(a) * 0.2, H + 0.18), (0.025, 0.07, ln / 2), (0.0, 1.0, a)))
        extra, leaf_objs = [], []
        if os.environ.get("ROOM_ATRIUM_HSSD") == "1":                       # O2 r23: tall dense planting from the HSSD scanned plants (banana, ficus, dracaena, palm ...) with real leaf thickness; the library species stay as the low layer
            try:
                import abo_assets, asset_pools
                pool_ = [e for e in asset_pools.pool("tall_plant") if e["triangles"] <= int(os.environ.get("ROOM_ATRIUM_HSSD_TRIS") or 45000)]
                drop_ = [x.lower() for x in (os.environ.get("ROOM_ATRIUM_HSSD_DROP") or "").split(",") if x]                  # O2-PLANTS: ROOM_ATRIUM_HSSD_DROP=banana drops the 13-16k-triangle banana trees (rigid flat leaf cards, straight tan trunk)
                pool_ = [e for e in pool_ if not any(x in str(e.get("name")).lower() for x in drop_)] or pool_
                if pool_:
                    hmax_ = float(pa.STYLE.get("atrium_tree_max_m") or 3.4)
                    nt_ = max(2, int(L // 1.3))
                    for k in range(nt_):
                        e_ = abo_assets.pick(r, pool_); o_ = abo_assets._import(e_, f"AtriumHssd{k}")
                        for sl_ in o_.material_slots:                          # O2 r24: the HSSD 'inferred' materials give some plant slots metallic ~0.98 / roughness 0.02 (mirrors reflecting the white sky: pure white leaves). A living plant is dielectric.
                            b_ = next((n_ for n_ in sl_.material.node_tree.nodes if n_.type == "BSDF_PRINCIPLED"), None) if sl_.material and sl_.material.node_tree else None
                            if b_ is not None:
                                if not sl_.material.get("ir_plant_fix"):
                                    sl_.material["ir_plant_fix"] = 1
                                    if b_.inputs["Metallic"].default_value > 0.2:
                                        b_.inputs["Metallic"].default_value = 0.0
                                    if b_.inputs["Roughness"].default_value < 0.35 and not b_.inputs["Roughness"].is_linked:
                                        b_.inputs["Roughness"].default_value = 0.5
                                    if "Coat Weight" in b_.inputs:
                                        b_.inputs["Coat Weight"].default_value = 0.0
                        tgt_ = min(r.uniform(1.8, 2.7), hmax_ - H - 0.3); hh_ = max(o_.dimensions.z, 1e-3); kk_ = tgt_ / hh_
                        mn_ = min(v.co.z for v in o_.data.vertices) * kk_
                        o_.scale = (kk_, kk_, kk_); o_.rotation_euler = (0, 0, r.uniform(0, 6.28))
                        o_.location = (D / 2 + r.uniform(-D * 0.2, D * 0.2), -L / 2 + (k + 0.5) * L / nt_ + r.uniform(-0.2, 0.2), H + 0.02 - mn_); leaf_objs.append(o_)
            except Exception as ex:                                          # noqa: BLE001 -- the library planting below still runs
                print(f"[atrium] hssd planting skipped: {ex!r}"[:160], flush=True)
        if pa.STYLE.get("atrium_big_plants"):                    # kit atrium_big_plants: a showpiece planting; Infinigen's own plants from data/plant_library_v2 when kit floor_plant_style is library_v2 / infinigen, else the procedural one (proc_office.atrium_planting)
            from room_planner import plant_lib2 as _pl2
            hmax = float(pa.STYLE.get("atrium_tree_max_m") or 3.4)
            if pa.STYLE.get("floor_plant_style") in ("library_v2", "infinigen") and _pl2.available():
                import math as _m2
                nt = max(1, int(L // 3.0))                                           # one tall banana accent per ~3 m of planter, a green mid layer and an under-planting between them
                for k in range(nt):
                    m_ = _pl2.pick("atrium", i * 31 + k, 0)
                    o_ = _pl2.load(m_, min(r.uniform(2.2, 2.8), hmax - H - 0.3), cap=80000, max_w=min(D * 1.6, 2.4), yaw=r.uniform(0, 6.28)) if m_ else None
                    if o_ is not None:
                        o_.location = (D / 2 + r.uniform(-D * 0.15, D * 0.15), -L / 2 + (k + 0.5) * L / nt + r.uniform(-0.3, 0.3), H + 0.02); leaf_objs.append(o_)
                for k in range(max(2, int(L * 0.7))):                                      # mid layer: taro / veratrum / agave, 1.0-1.8 m
                    m_ = _pl2.pick("atrium_mid", i * 23 + k, 2)
                    o_ = _pl2.load(m_, r.uniform(1.0, 1.8), cap=40000, max_w=1.3, yaw=r.uniform(0, 6.28)) if m_ else None
                    if o_ is not None:
                        o_.location = (D / 2 + r.uniform(-D * 0.3, D * 0.3), -L / 2 + 0.4 + r.random() * (L - 0.8), H + 0.02); leaf_objs.append(o_)
                for k in range(max(2, int(L * 1.2))):
                    m_ = _pl2.pick("atrium_under", i * 17 + k, 1)
                    o_ = _pl2.load(m_, r.uniform(0.6, 1.1), cap=20000, max_w=0.9, yaw=r.uniform(0, 6.28)) if m_ else None
                    if o_ is not None:
                        o_.location = (D / 2 + r.uniform(-D * 0.35, D * 0.35), -L / 2 + 0.3 + r.random() * (L - 0.6), H + 0.02); leaf_objs.append(o_)
            # (the procedural palms stay as the tree layer: the library has no palm tree, only fronds; it adds green taro, ferns, snake plants and a banana accent)
            if not leaf_objs:
                from room_planner import proc_office as _po
                r_ = _po.atrium_planting(r, L, D, H, pa.STYLE.get("atrium_tree_max_m"))
                if isinstance(r_, tuple):
                    extra, lo_ = r_; leaf_objs.append(lo_)
                else:
                    extra = r_
        o = pa._prims(f"AtriumPlanterFactory({i}).spawn_asset({i})", [(stone, box), (peb, top), (trunk, trunks), (g1, fa), (g2, fb)] + extra)
        return pa._join_cloth(o, leaf_objs) if leaf_objs else o


class DrumPendantFactory:
    """A large fabric DRUM pendant (P2b living ref: 'fabric drum pendants', ours: small surface domes): 0.7 m wide, 0.28 m tall cream fabric shade (translucent, softly emissive) on two cords with a thin brass cap; origin at the
    ceiling point, hangs `drop` m."""

    def __init__(self, seed=0, drop=0.7):
        self.drop = drop

    def spawn_asset(self, i):
        fab = fl._flat("ir_dp_fabric", (0.93, 0.9, 0.82), 0.9); b = fab.node_tree.nodes["Principled BSDF"]
        b.inputs["Emission Color"].default_value = (1.0, 0.9, 0.72, 1); b.inputs["Emission Strength"].default_value = 0.9
        brass = fl._flat("ir_dp_brass", (0.78, 0.6, 0.25), 0.3, 1.0)
        d = self.drop
        return mesh_object(f"DrumPendantFactory({i}).spawn_asset({i})", [(fab, [("cyl", (0, 0, -d - 0.14), (0, 0, -d + 0.14), 0.35, 36)]), (brass, [("cyl", (0, 0, -d / 2), (0, 0, 0.0), 0.004, 6), ("cyl", (0, 0, -0.02), (0, 0, 0.0), 0.05, 12)])], bevel=False)


class FloorDrainFactory:
    """A floor drain (G / H utility refs): a 0.2 m round stainless grate, 1 cm proud, with a slotted pattern; origin on the floor at its centre."""

    def __init__(self, seed=0):
        pass

    def spawn_asset(self, i):
        steel = fl._flat("ir_fd_steel", (0.55, 0.56, 0.58), 0.35, 1.0); dark = fl._flat("ir_fd_dark", (0.03, 0.03, 0.035), 0.6)
        slots = [("box", (0.0, y, 0.011), (0.14, 0.012, 0.004), (0, 0, 0)) for y in (-0.05, -0.025, 0.0, 0.025, 0.05)]
        return pa._prims(f"FloorDrainFactory({i}).spawn_asset({i})", [(steel, [("cyl", (0, 0, 0.005), (0.1, 0.1, 0.01), (0, 0, 0))]), (dark, slots)])


class OvenTowerFactory:
    """A built-in oven + microwave tower (P2b kitchen ref: 'oven and microwave stack'): 0.62 x 0.6 x 2.1 m, back at x = 0, front +X: a cream (kit kitchen_front) carcass, a drawer at the foot, a steel-framed oven with a dark glass
    door and a bar handle at 0.75-1.3 m, a microwave with a dark door and a control strip at 1.4-1.8 m, a cabinet above."""

    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        rgb = HomeKitchenRunFactory.FRONTS.get(pa.STYLE.get("kitchen_front"), (0.9, 0.9, 0.88))
        body = fl._flat("ir_ot_body", rgb, 0.45); steel = fl._flat("ir_ot_steel", (0.72, 0.73, 0.75), 0.25, 1.0); glass = fl._flat("ir_ot_glass", (0.03, 0.03, 0.035), 0.08)
        W, D, H = 0.6, 0.62, 2.1
        parts_b = [("box", D / 2, 0, H / 2, D, W, H), ("box", D + 0.006, 0, 0.35, 0.012, W - 0.04, 0.56), ("box", D + 0.006, 0, 1.95, 0.012, W - 0.04, 0.3)]
        steel_p = [("box", D + 0.01, 0, 1.03, 0.02, W - 0.04, 0.56), ("box", D + 0.025, 0, 1.28, 0.012, 0.4, 0.012), ("box", D + 0.01, 0, 1.6, 0.02, W - 0.04, 0.4), ("box", D + 0.02, 0, 0.62, 0.012, 0.3, 0.012)]
        glass_p = [("box", D + 0.022, 0, 1.0, 0.006, W - 0.14, 0.4), ("box", D + 0.022, -0.04, 1.6, 0.006, W - 0.2, 0.3)]
        strip = [("box", D + 0.022, 0.22, 1.6, 0.006, 0.07, 0.3), ("cyl", (D + 0.022, 0.22, 1.7), (D + 0.03, 0.22, 1.7), 0.012, 10)]
        return mesh_object(f"OvenTowerFactory({i}).spawn_asset({i})", [(body, parts_b), (steel, steel_p + strip), (glass, glass_p)], bevel=False)


class BarPortalFactory:
    """The cottage bar's raised rear zone (S33 ref): a wide honey-timber PORTAL frame (two 18 cm posts + a 30 cm lintel, 4.2 m span, 2.4 m high) with a low dark-stone step along its foot on the bar side. Front +X
    (the seating side), origin at the frame's centre on the floor. The step is 0.16 m high x 0.55 m deep (x -0.55 .. 0): the raised zone's edge."""

    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        wood = fl._flat("ir_portal_wood", (0.5, 0.26, 0.08), 0.5, wood=True); stone = fl._flat("ir_portal_stone", (0.05, 0.05, 0.055), 0.8)
        L, H = 4.2, 2.4
        posts = [("box", (0, sy * (L / 2 - 0.09), H / 2), (0.2, 0.18, H), (0, 0, 0)) for sy in (1, -1)]
        lintel = [("box", (0, 0, H - 0.15), (0.22, L, 0.3), (0, 0, 0))]
        step = [("box", (-0.3, 0, 0.08), (0.55, L - 0.36, 0.16), (0, 0, 0))]
        return pa._prims(f"BarPortalFactory({i}).spawn_asset({i})", [(wood, posts + lintel), (stone, step)])


class StandingAcFactory:
    """A freestanding floor air-conditioner cabinet (S33 ref): 0.32 x 0.5 x 1.75 m white, a louvred grille panel high on the front and a small dark display, back at x = 0, front +X."""

    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        white = fl._flat("ir_sac_white", (0.9, 0.9, 0.88), 0.45); grey = fl._flat("ir_sac_grille", (0.6, 0.62, 0.64), 0.4); dark = fl._flat("ir_sac_dark", (0.03, 0.03, 0.035), 0.3)
        body = [("rbox", (0.16, 0, 0.88), (0.32, 0.5, 1.75), (0, 0, 0))]
        grille = [("box", (0.325, 0, 1.45 - 0.045 * k), (0.01, 0.4, 0.012), (0, 0, 0)) for k in range(6)]
        disp = [("box", (0.325, 0, 1.0), (0.01, 0.12, 0.05), (0, 0, 0))]
        return pa._prims(f"StandingAcFactory({i}).spawn_asset({i})", [(white, body), (grey, grille), (dark, disp)])


class FoodStallRowFactory:
    """A row of three red food-court stalls with striped awnings (M refs: 'multiple red-and-white food stalls and striped awnings'): 6.0 m long x 1.4 m deep x 2.7 m high, back wall at x = 0, front +X. Each 2.0 m
    stall: a red counter with a white top, a dark back wall with a cream menu board, two white front posts, a red/white striped awning sloping down to the front with a striped valance."""

    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        import math as _m
        red = fl._flat("ir_fs_red", (0.62, 0.05, 0.04), 0.5); white = fl._flat("ir_fs_white", (0.9, 0.9, 0.88), 0.5); dark = fl._flat("ir_fs_dark", (0.07, 0.06, 0.06), 0.7); cream = fl._flat("ir_fs_menu", (0.9, 0.84, 0.66), 0.8)
        steel = fl._flat("ir_fs_steel", (0.62, 0.64, 0.66), 0.3, 1.0)
        W, n = 2.0, 3
        rd, wh, dk, cr, st = [], [], [], [], []
        for k in range(n):
            y = (k - (n - 1) / 2) * W
            rd += [("box", (0.75, y, 0.5), (0.5, W - 0.06, 1.0), (0, 0, 0))]                              # counter body
            wh += [("box", (0.75, y, 1.02), (0.58, W - 0.02, 0.05), (0, 0, 0))]                          # worktop
            wh += [("box", (1.1, y + sy * (W / 2 - 0.05), 1.35), (0.06, 0.06, 2.7), (0, 0, 0)) for sy in (1, -1)]    # front posts
            dk += [("box", (0.05, y, 1.35), (0.1, W - 0.06, 2.7), (0, 0, 0))]                            # back wall
            cr += [("box", (0.11, y, 1.95), (0.02, 1.1, 0.5), (0, 0, 0))]                                # menu board
            st += [("box", (0.45, y, 1.07), (0.5, 1.2, 0.04), (0, 0, 0))]                                # steel prep table
            ang = _m.atan2(0.5, 1.1)                                                                       # awning drops 0.5 m over its 1.1 m projection
            ln = _m.hypot(1.1, 0.5)
            m = 10
            for s in range(m):
                ys = y - W / 2 + (s + 0.5) * W / m
                (rd if s % 2 == 0 else wh).append(("box", (0.65, ys, 2.55), (ln, W / m - 0.002, 0.03), (0, ang, 0)))      # striped awning slope
                (rd if s % 2 == 0 else wh).append(("box", (1.2, ys, 2.2), (0.03, W / m - 0.002, 0.2), (0, 0, 0)))          # striped valance
        return pa._prims(f"FoodStallRowFactory({i}).spawn_asset({i})", [(red, rd), (white, wh), (dark, dk), (cream, cr), (steel, st)])
