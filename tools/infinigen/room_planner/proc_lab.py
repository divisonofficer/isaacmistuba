"""Props for the university research-building corridor (floor N, refs out/room_planner_refs/lab_corridor_0127; docs/lab_corridor_design_proposal.md). Factory-shaped (Cls(seed).spawn_asset(i), front +X).

  GasCylinderRackFactory   a steel rack (0.7 x 1.2 x 1.3 m) chaining 4-8 grey gas cylinders with coloured shoulders and a yellow paper tag
  LabChamberFactory        a white equipment cabinet / environmental chamber (0.8 x 1.4 x 2.0 m): glass-panel doors, dark control panel, blue indicator strip
  FireExtinguisherFactory  a red extinguisher (0.16 x 0.16 x 0.55 m) with a black hose and a small sign plate
  NoticePanelFactory       a wall notice panel (0.04 x 0.6 x 0.85 m, origin at the bottom): green board with rows of printed lines (no real text)
  VendingMachineFactory    a beverage vending machine (0.8 x 0.9 x 1.85 m): white body, lit front panel, button column
  WaterDispenserFactory    a floor water dispenser (0.34 x 0.34 x 1.05 m): white body, blue and red taps, a tray
  FireDoorFactory          a beige steel double door leaf standing open at 90 deg (0.12 x 1.0 x 2.1 m; the closed leaf's hinge at y = 0), lever handle
  GlassDoubleDoorFactory   a stainless-framed glass double door (0.12 x 2.0 x 2.3 m) with two vertical blue LED strips
"""
from __future__ import annotations

import math
import os
import random

from room_planner import proc_boutique_flagship as fl
from room_planner.proc_boutique_flagship import mesh_object


def _emit(name, rgb, strength):
    m = fl._flat(name, rgb, 0.3)
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Emission Color"].default_value = (*rgb, 1.0); b.inputs["Emission Strength"].default_value = strength
    return m


class GasCylinderRackFactory:
    def __init__(self, seed):
        self.r = random.Random(seed); self.n = self.r.randint(4, 8)

    def spawn_asset(self, i):
        r = self.r
        steel = fl._flat("ir_lab_rack_steel", (0.35, 0.36, 0.38), 0.45, 0.9); body = fl._flat("ir_lab_cyl_body", (0.28, 0.29, 0.3), 0.4, 0.8)
        tag = fl._flat("ir_lab_tag", (0.95, 0.82, 0.3), 0.7); col = [fl._flat(f"ir_lab_cyl_cap_{k}", c, 0.45, 0.4) for k, c in enumerate(((0.1, 0.3, 0.7), (0.2, 0.5, 0.2), (0.7, 0.15, 0.12), (0.85, 0.75, 0.2)))]
        W, D = 1.2, 0.7
        frame = [("box", 0.0, 0.0, 0.06, D, W, 0.04), ("box", D / 2 - 0.02, 0.0, 0.85, 0.03, W, 0.05), ("box", -D / 2 + 0.02, 0.0, 0.85, 0.03, W, 0.05)]
        frame += [("cyl", (sx * (D / 2 - 0.02), sy * (W / 2 - 0.02), 0.0), (sx * (D / 2 - 0.02), sy * (W / 2 - 0.02), 1.3), 0.02, 8) for sx in (1, -1) for sy in (1, -1)]
        from room_planner import proc_assets as pa
        R0 = (0, 0, 0)
        cyl, necks, valves, gauges, chain, caps, tags = [], [], [], [], [], {}, []
        for k in range(self.n):
            cx = (-0.17 if k % 2 == 0 else 0.17); cy = -W / 2 + 0.17 + (k // 2) * (W - 0.34) / max(1, (self.n + 1) // 2 - 1) if self.n > 2 else 0.0
            h = r.uniform(1.15, 1.35); top = 0.08 + h * 0.84
            cyl.append(("cyl", (cx, cy, 0.08 + (top - 0.08) / 2), (0.1, 0.1, top - 0.08), R0))           # the body
            cyl.append(("sph", (cx, cy, top), (0.1, 0.1, 0.075), R0))                                     # a ROUND shoulder (G-bay r4: 'faceted with pyramid tops')
            necks.append(("cyl", (cx, cy, top + 0.09), (0.03, 0.03, 0.09), R0))
            valves.append(("box", (cx, cy, top + 0.17), (0.07, 0.06, 0.07), R0)); valves.append(("cyl", (cx + 0.05, cy, top + 0.17), (0.015, 0.015, 0.06), (0, 1.5708, 0)))
            gauges += [("cyl", (cx, cy + 0.07, top + 0.14), (0.035, 0.035, 0.02), (1.5708, 0, 0)), ("cyl", (cx, cy - 0.07, top + 0.14), (0.035, 0.035, 0.02), (1.5708, 0, 0))]
            c = r.choice(col); caps.setdefault(c, []).append(("cyl", (cx, cy, top - 0.12), (0.1015, 0.1015, 0.16), R0))
            if r.random() < 0.5:
                tags.append(("box", (cx + 0.1, cy, 0.08 + h * 0.5), (0.005, 0.1, 0.14), (0, 0, r.uniform(-0.3, 0.3))))
        for x_ in (-0.17, 0.17):                                                                          # the safety chain across each column of cylinders
            chain.append(("cyl", (x_, 0.0, 0.9), (0.006, 0.006, W - 0.1), (1.5708, 0, 0)))
        fr = [("box", (0.0, 0.0, 0.06), (D, W, 0.04), R0), ("box", (D / 2 - 0.02, 0.0, 0.85), (0.03, W, 0.05), R0), ("box", (-D / 2 + 0.02, 0.0, 0.85), (0.03, W, 0.05), R0)]
        fr += [("cyl", (sx * (D / 2 - 0.02), sy * (W / 2 - 0.02), 0.65), (0.02, 0.02, 1.3), R0) for sx in (1, -1) for sy in (1, -1)]
        groups = [(steel, fr + necks + valves + chain), (body, cyl), (tag, tags), (steel, gauges)] + [(c, p) for c, p in caps.items()]
        o = pa._prims(f"GasCylinderRackFactory({i}).spawn_asset({i})", groups)
        for p_ in o.data.polygons:
            if p_.material_index in (1,) or p_.material_index >= 4:
                p_.use_smooth = True
        return o

class LabChamberFactory:
    def __init__(self, seed):
        self.r = random.Random(seed); self.H = self.r.uniform(1.8, 2.1); self.W = self.r.choice((1.0, 1.4))

    def spawn_asset(self, i):
        w = fl._flat("ir_lab_white", (0.86, 0.87, 0.86), 0.4); dark = fl._flat("ir_lab_glass", (0.05, 0.06, 0.08), 0.1, 0.4); led = _emit("ir_lab_led_blue", (0.2, 0.45, 1.0), 6.0)
        D, W, H = 0.8, self.W, self.H
        parts = [(w, [("box", 0, 0, H / 2, D, W, H)]),
                 (dark, [("box", D / 2 + 0.006, -W * 0.22, H * 0.5, 0.012, W * 0.42, H * 0.62), ("box", D / 2 + 0.006, W * 0.22, H * 0.5, 0.012, W * 0.42, H * 0.62), ("box", D / 2 + 0.006, 0, H * 0.9, 0.012, W * 0.8, 0.14)]),
                 (led, [("box", D / 2 + 0.012, 0, H * 0.9, 0.006, W * 0.5, 0.02)])]
        return mesh_object(f"LabChamberFactory({i}).spawn_asset({i})", parts, bevel=True)


class FireExtinguisherFactory:
    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        red = fl._flat("ir_fe_red", (0.72, 0.08, 0.06), 0.35, 0.3); blk = fl._flat("ir_fe_black", (0.03, 0.03, 0.03), 0.5); plate = fl._flat("ir_fe_plate", (0.9, 0.9, 0.85), 0.5)
        return mesh_object(f"FireExtinguisherFactory({i}).spawn_asset({i})",
                           [(red, [("cyl", (0, 0, 0.02), (0, 0, 0.4), 0.08, 12), ("sph", (0, 0, 0.4), 0.08, 1)]),
                            (blk, [("cyl", (0, 0, 0.44), (0, 0, 0.5), 0.025, 8), ("cyl", (0.04, 0, 0.3), (0.12, 0, 0.5), 0.008, 6)]),
                            (plate, [("box", 0.081, 0, 0.26, 0.004, 0.09, 0.1)])], bevel=False)


class NoticePanelFactory:
    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        r = self.r; board = fl._flat("ir_lab_notice_green", (0.12, 0.42, 0.22), 0.6); line = fl._flat("ir_lab_notice_line", (0.9, 0.92, 0.88), 0.7)
        W, H = 0.6, 0.85
        lines = [("box", 0.026, 0, 0.1 + 0.052 * k, 0.004, W * r.uniform(0.55, 0.85), 0.012) for k in range(int((H - 0.2) / 0.052))]
        return mesh_object(f"NoticePanelFactory({i}).spawn_asset({i})", [(board, [("box", 0.015, 0, H / 2, 0.03, W, H)]), (line, lines)], bevel=False)


class VendingMachineFactory:
    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        w = fl._flat("ir_vend_white", (0.9, 0.9, 0.88), 0.35); glow = _emit("ir_vend_glow", (0.85, 0.95, 1.0), 4.0); dk = fl._flat("ir_vend_dark", (0.06, 0.06, 0.07), 0.4, 0.4)
        D, W, H = 0.8, 0.9, 1.85
        btn = [("box", D / 2 + 0.008, 0.33, 0.7 + 0.1 * k, 0.012, 0.07, 0.05) for k in range(6)]
        cols = [fl._flat(f"ir_vend_prod_{k}", c, 0.4) for k, c in enumerate(((0.8, 0.12, 0.1), (0.1, 0.3, 0.7), (0.95, 0.75, 0.1), (0.15, 0.55, 0.25), (0.85, 0.5, 0.15), (0.9, 0.9, 0.9)))]
        prods = [[] for _ in cols]
        for row in range(5):                                       # the lit window shows products (N2 r7: 'vending face should show products'): five shelves of cans and snack packs, each row mostly one colour
            base = r_ = self.r.randrange(len(cols)); zr = 0.68 + 0.215 * row
            for k in range(6):
                c_ = base if self.r.random() < 0.7 else self.r.randrange(len(cols))
                prods[c_].append(("box", D / 2 + 0.02, -0.34 + 0.092 * k, zr + 0.06, 0.02, 0.06, 0.12))
                prods[c_].append(("box", D / 2 + 0.012, -0.34 + 0.092 * k, zr - 0.01, 0.01, 0.075, 0.012))            # a shelf lip
        return mesh_object(f"VendingMachineFactory({i}).spawn_asset({i})",
                           [(w, [("box", 0, 0, H / 2, D, W, H)]), (glow, [("box", D / 2 + 0.006, -0.12, 1.15, 0.01, 0.55, 1.2)]),
                            (dk, [("box", D / 2 + 0.008, 0.33, 0.35, 0.012, 0.2, 0.1)] + btn)] + [(cols[k], pp) for k, pp in enumerate(prods) if pp], bevel=True)


class WaterDispenserFactory:
    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        w = fl._flat("ir_wd_white", (0.93, 0.94, 0.93), 0.3); blue = fl._flat("ir_wd_blue", (0.1, 0.35, 0.8), 0.4); red = fl._flat("ir_wd_red", (0.8, 0.12, 0.1), 0.4); steel = fl._flat("ir_wd_tray", (0.7, 0.7, 0.72), 0.3, 0.9)
        return mesh_object(f"WaterDispenserFactory({i}).spawn_asset({i})",
                           [(w, [("box", 0, 0, 0.52, 0.34, 0.34, 1.04)]), (blue, [("box", 0.18, -0.05, 0.85, 0.04, 0.04, 0.04)]), (red, [("box", 0.18, 0.05, 0.85, 0.04, 0.04, 0.04)]),
                            (steel, [("box", 0.17, 0, 0.74, 0.08, 0.2, 0.012)])], bevel=True)


class FireDoorFactory:
    """Open at 90 deg: the leaf stands in the x direction from the hinge (0, 0), its front +X (the hinge side at y = 0 is on the wall)."""
    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        beige = fl._flat("ir_firedoor_beige", (0.78, 0.74, 0.62), 0.5, 0.2); steel = fl._flat("ir_firedoor_steel", (0.6, 0.6, 0.62), 0.3, 0.9)
        return mesh_object(f"FireDoorFactory({i}).spawn_asset({i})",
                           [(beige, [("box", 0.5, 0.04, 1.05, 1.0, 0.045, 2.1)]), (steel, [("box", 0.86, 0.075, 1.0, 0.12, 0.03, 0.03), ("box", 0.02, 0.04, 0.4, 0.04, 0.06, 0.12), ("box", 0.02, 0.04, 1.7, 0.04, 0.06, 0.12)])], bevel=False)


class GlassDoubleDoorFactory:
    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        steel = fl._flat("ir_gd_steel", (0.7, 0.7, 0.72), 0.3, 0.9); glass = fl._flat("ir_gd_glass", (0.05, 0.07, 0.09), 0.05, 0.3); led = _emit("ir_gd_led", (0.25, 0.6, 1.0), 8.0)
        W, H = 2.0, 2.3
        fr = [("box", 0, 0, 0.04, 0.1, W, 0.08), ("box", 0, 0, H - 0.04, 0.1, W, 0.08), ("box", 0, -W / 2 + 0.03, H / 2, 0.1, 0.06, H), ("box", 0, W / 2 - 0.03, H / 2, 0.1, 0.06, H), ("box", 0, 0, H / 2, 0.1, 0.05, H)]
        return mesh_object(f"GlassDoubleDoorFactory({i}).spawn_asset({i})",
                           [(steel, fr), (glass, [("box", 0, 0, H / 2, 0.02, W - 0.12, H - 0.16)]), (led, [("box", 0.07, sy * 0.45, 1.05, 0.012, 0.03, 0.9) for sy in (-1, 1)])], bevel=False)


class LabCabinetFactory:
    """A tall laboratory cabinet (N r3 review: 'dense lab cabinets along the corridor walls'): 0.55 x 1.2 x 2.1 m, front +X, back at x = 0: white steel carcase, two lower drawers, glass upper doors showing rows of
    bottles / boxes, a dark handle rail; colour variants (white / light grey / pale blue)."""

    def __init__(self, seed):
        self.r = random.Random(seed); self.col = self.r.choice(((0.9, 0.9, 0.88), (0.78, 0.8, 0.82), (0.72, 0.82, 0.88)))

    def spawn_asset(self, i):
        r = self.r; body = fl._flat(f"ir_labcab_{int(self.col[0] * 100)}_{int(self.col[2] * 100)}", self.col, 0.4); dark = fl._flat("ir_labcab_dark", (0.06, 0.06, 0.07), 0.5)
        glass = fl._flat("ir_labcab_glass", (0.75, 0.85, 0.9), 0.05, transmission=0.6) if False else fl._flat("ir_labcab_glassc", (0.55, 0.68, 0.75), 0.1)
        W, D, H = 1.2, 0.55, 2.1
        carcase = [("box", D / 2, 0, H / 2, D, W, H)]
        face = [("box", D + 0.005, 0, 0.5, 0.01, W - 0.06, 0.9), ("box", D + 0.005, 0, 0.98, 0.012, W - 0.04, 0.02)]
        upper = [("box", D + 0.006, 0, 1.58, 0.01, W - 0.08, 1.0)]
        handles = [("box", D + 0.02, sy * 0.25, 0.65, 0.02, 0.35, 0.025) for sy in (-1, 1)] + [("box", D + 0.02, sy * 0.25, 0.3, 0.02, 0.35, 0.025) for sy in (-1, 1)]
        items = {}
        for row in range(3):
            for k in range(r.randint(5, 8)):
                c = r.choice(((0.9, 0.55, 0.1), (0.2, 0.45, 0.8), (0.9, 0.9, 0.85), (0.45, 0.25, 0.1), (0.2, 0.55, 0.3)))
                items.setdefault(c, []).append(("box", D - 0.18, -W / 2 + 0.12 + k * (W - 0.24) / 7 + r.uniform(-0.02, 0.02), 1.22 + row * 0.3 + 0.08, 0.1, 0.07, 0.16))
        groups = [(body, carcase + face), (dark, handles), (fl._flat("ir_labcab_panel", (0.35, 0.45, 0.5), 0.2), upper)] + \
                 [(fl._flat(f"ir_labcab_item_{int(c[0] * 100)}_{int(c[1] * 100)}_{int(c[2] * 100)}", c, 0.5), ps) for c, ps in items.items()]
        return mesh_object(f"LabCabinetFactory({i}).spawn_asset({i})", groups, bevel=False)


class GasCylinderCartFactory:
    """A gas-cylinder cart (0.6 x 0.9 x 1.5 m): a steel two-wheel / castor frame carrying two grey cylinders with coloured shoulders, a chain, a regulator on each."""
    COLS = ((0.2, 0.45, 0.8), (0.85, 0.2, 0.15), (0.2, 0.6, 0.3), (0.95, 0.75, 0.1), (0.9, 0.9, 0.9))

    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        r = self.r; steel = fl._flat("ir_cart_steel", (0.3, 0.3, 0.32), 0.4, 0.9); grey = fl._flat("ir_cyl_grey", (0.55, 0.57, 0.6), 0.35, 0.8); black = fl._flat("ir_cart_wheel", (0.04, 0.04, 0.04), 0.7)
        parts = [("box", 0.0, 0.0, 0.18, 0.5, 0.9, 0.04), ("box", -0.22, 0.0, 0.75, 0.04, 0.88, 0.04), ("box", -0.25, -0.44, 0.75, 0.05, 0.04, 1.2), ("box", -0.25, 0.44, 0.75, 0.05, 0.04, 1.2), ("box", 0.2, 0.0, 0.7, 0.02, 0.86, 0.025)]
        cyl, shoulder, regs = [], {}, []
        for k, y in enumerate((-0.22, 0.22)):
            cyl.append(("cyl", (0.0, y, 0.2), (0.0, y, 1.1), 0.1, 28))
            c = r.choice(self.COLS); shoulder.setdefault(c, []).append(("cyl", (0.0, y, 1.1), (0.0, y, 1.26), 0.1, 28))
            regs.append(("box", 0.0, y, 1.33, 0.07, 0.07, 0.1))
        wheels = [("cyl", (-0.3, sy * 0.35, 0.1), (-0.3, sy * 0.35 + sy * 0.04, 0.1), 0.1, 12) for sy in (1, -1)] + [("cyl", (0.2, sy * 0.35, 0.06), (0.2, sy * 0.35 + sy * 0.03, 0.06), 0.06, 10) for sy in (1, -1)]
        groups = [(steel, parts + regs), (grey, cyl), (black, wheels)] + [(fl._flat(f"ir_cyl_sh_{int(c[0] * 100)}_{int(c[1] * 100)}", c, 0.4), ps) for c, ps in shoulder.items()]
        o = mesh_object(f"GasCylinderCartFactory({i}).spawn_asset({i})", groups, bevel=False)
        for p_ in o.data.polygons:                                                      # smooth cylinders + shoulders (the facets read as 'faceted gas cylinders')
            if p_.material_index == 1 or p_.material_index >= 3:
                p_.use_smooth = True
        return o


class DoorSafetySignFactory:
    """A lab door safety sign board (0.02 x 0.32 x 0.46 m, origin at the bottom): a white board with a coloured header, 3 hazard pictogram squares (yellow / blue / red-white) and printed-line bars."""

    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        r = self.r; white = fl._flat("ir_ds_white", (0.92, 0.92, 0.9), 0.5); head = fl._flat("ir_ds_head", r.choice(((0.1, 0.45, 0.25), (0.8, 0.15, 0.1), (0.1, 0.3, 0.7))), 0.5)
        yel = fl._flat("ir_ds_yel", (0.95, 0.8, 0.1), 0.5); blu = fl._flat("ir_ds_blu", (0.1, 0.3, 0.7), 0.5); red = fl._flat("ir_ds_red", (0.8, 0.12, 0.1), 0.5); ink = fl._flat("ir_ds_ink", (0.1, 0.1, 0.12), 0.6)
        groups = [(white, [("box", 0.01, 0, 0.23, 0.02, 0.32, 0.46)]), (head, [("box", 0.021, 0, 0.42, 0.004, 0.32, 0.08)]), (yel, [("box", 0.022, -0.1, 0.3, 0.004, 0.08, 0.08)]),
                  (blu, [("box", 0.022, 0.0, 0.3, 0.004, 0.08, 0.08)]), (red, [("box", 0.022, 0.1, 0.3, 0.004, 0.08, 0.08)]),
                  (ink, [("box", 0.022, 0, 0.18 - 0.05 * k, 0.003, 0.26 * r.uniform(0.6, 1.0), 0.015) for k in range(3)])]
        return mesh_object(f"DoorSafetySignFactory({i}).spawn_asset({i})", groups, bevel=False)


class OpticalTableFactory:
    """A stainless OPTICAL TABLE with optical assemblies (N2 lab refs: 'stainless optical tables with optical assemblies / mounts'): 2.4 x 1.2 x 0.8 m, a thick steel top with a 25 mm hole grid, four isolator legs, a low rail frame;
    on top: a dark laser head with a status LED, 6-9 post-mounted mirrors / lenses on a few hole positions, two beam splitter cubes, a power meter on a stand and thin red beam lines between them. Origin at the footprint centre
    on the floor, length along local y."""

    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        from room_planner import proc_assets as pa
        import math as _m
        r = self.r
        steel = fl._flat("ir_ot_steel", (0.72, 0.73, 0.75), 0.3, 1.0); dark = fl._flat("ir_ot_dark", (0.03, 0.03, 0.035), 0.5); black = fl._flat("ir_ot_hole", (0.1, 0.1, 0.11), 0.6)
        glass = fl._flat("ir_ot_optic", (0.7, 0.85, 0.9), 0.05); beam = _emit("ir_ot_beam", (1.0, 0.1, 0.05), 20.0); led = _emit("ir_ot_led", (0.1, 1.0, 0.3), 10.0); alu = fl._flat("ir_ot_alu", (0.85, 0.86, 0.88), 0.25, 1.0)
        W, L, H = 1.2, 2.4, 0.8
        R0 = (0, 0, 0)
        top = [("box", (0, 0, H - 0.05), (W, L, 0.1), R0)]
        frame = [("box", (0, 0, 0.45), (W - 0.1, L - 0.1, 0.05), R0)] + [("cyl", (sx * (W / 2 - 0.1), sy * (L / 2 - 0.12), 0.35), (0.06, 0.06, 0.7), R0) for sx in (1, -1) for sy in (1, -1)]
        holes = [("cyl", (-W / 2 + 0.1 + a * 0.1, -L / 2 + 0.1 + b * 0.1, H + 0.001), (0.005, 0.005, 0.002), R0) for a in range(11) for b in range(23) if (a * 7 + b * 3) % 4 == 0]
        laser = [("box", (-0.35, -L / 2 + 0.28, H + 0.07), (0.16, 0.45, 0.14), R0)]
        leds = [("cyl", (-0.35, -L / 2 + 0.52, H + 0.1), (0.01, 0.01, 0.01), R0)]
        posts, mirrors, cubes, beams = [], [], [], []
        pts = [(-0.35, -L / 2 + 0.5)]                                                          # the beam path: a polyline of mounts
        for k in range(8):
            a = -0.4 + (k % 4) * 0.27 + r.uniform(-0.03, 0.03); b = -L / 2 + 0.6 + k * 0.22 + r.uniform(-0.03, 0.03)
            pts.append((a, b)); posts.append(("cyl", (a, b, H + 0.05), (0.0125, 0.0125, 0.1), R0)); posts.append(("cyl", (a, b, H + 0.01), (0.03, 0.03, 0.02), R0))
            mirrors.append(("cyl", (a, b, H + 0.13), (0.0255, 0.0255, 0.012), (0, 1.5708, r.uniform(0, 3.14))))
        for k in range(2):
            a = 0.3 - k * 0.3; b = -0.2 + k * 0.7
            cubes.append(("box", (a, b, H + 0.06), (0.025, 0.025, 0.025), R0)); posts.append(("cyl", (a, b, H + 0.025), (0.0125, 0.0125, 0.05), R0))
        meter = [("box", (0.4, L / 2 - 0.25, H + 0.1), (0.1, 0.1, 0.05), R0), ("cyl", (0.4, L / 2 - 0.25, H + 0.04), (0.012, 0.012, 0.08), R0)]
        for p0, p1 in zip(pts[:-1], pts[1:]):
            dx, dy = p1[0] - p0[0], p1[1] - p0[1]; ln = _m.hypot(dx, dy)
            beams.append(("cyl", ((p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2, H + 0.13), (0.0015, 0.0015, ln), (-_m.pi / 2, 0, -_m.atan2(dx, dy) + 0.0)))
        groups = [(steel, top + frame), (black, holes), (dark, laser + meter), (led, leds), (alu, posts + cubes), (glass, mirrors), (beam, beams if os.environ.get("ROOM_LAB_BEAMS") == "1" else [])]
        o = pa._prims(f"OpticalTableFactory({i}).spawn_asset({i})", groups)
        return o


class VacuumChamberFactory:
    """A horizontal stainless vacuum chamber on a frame with CF flanges, a viewport and a roughing line (N2 lab refs): 1.3 x 0.8 x 1.4 m; back at x = 0."""

    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        from room_planner import proc_assets as pa
        steel = fl._flat("ir_vc_steel", (0.74, 0.75, 0.77), 0.28, 1.0); dark = fl._flat("ir_vc_dark", (0.05, 0.05, 0.06), 0.5); glass = fl._flat("ir_vc_glass", (0.25, 0.4, 0.5), 0.05)
        blue = fl._flat("ir_vc_blue", (0.1, 0.25, 0.7), 0.5)
        R0 = (0, 0, 0); RY = (0, 1.5708, 0); RX = (1.5708, 0, 0)
        body = [("cyl", (0.5, 0, 0.85), (0.38, 0.38, 1.0), RX)]
        flanges = [("cyl", (0.5, y, 0.85), (0.46, 0.46, 0.04), RX) for y in (-0.52, 0.52)]
        ports = [("cyl", (0.5, 0, 1.3), (0.09, 0.09, 0.22), R0), ("cyl", (0.5, 0, 1.43), (0.13, 0.13, 0.03), R0), ("cyl", (0.88, 0.0, 0.85), (0.09, 0.09, 0.2), RY), ("cyl", (0.99, 0, 0.85), (0.13, 0.13, 0.03), RY)]
        vp = [("cyl", (0.5, -0.545, 0.85), (0.14, 0.14, 0.02), RX)]
        frame = [("box", (0.5, 0, 0.4), (0.9, 0.9, 0.06), R0)] + [("box", (0.5 + sx * 0.4, sy * 0.4, 0.2), (0.05, 0.05, 0.4), R0) for sx in (1, -1) for sy in (1, -1)]
        pump = [("cyl", (0.5, 0.75, 0.3), (0.12, 0.12, 0.6), R0), ("cyl", (0.5, 0.45, 0.62), (0.03, 0.03, 0.5), RX)]
        ctrl = [("box", (0.2, 0.0, 1.2), (0.12, 0.35, 0.28), R0)]
        o = pa._prims(f"VacuumChamberFactory({i}).spawn_asset({i})", [(steel, body + flanges + ports + frame + pump), (glass, vp), (dark, ctrl), (blue, [("box", (0.26, 0.0, 1.22), (0.01, 0.25, 0.1), R0)])])
        for p_ in o.data.polygons:
            if p_.material_index == 0:
                p_.use_smooth = True
        return o


class InstrumentRackFactory:
    """A 19-inch instrument rack (N2 lab refs: 'instrument monitors / control panels'): black steel frame 0.6 x 0.8 x 1.9 m with 7-9 stacked front units - each a dark panel with LEDs, knobs and a small display - and a
    side cable bundle. Front +X, back at x = 0."""

    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        from room_planner import proc_assets as pa
        r = self.r
        frame = fl._flat("ir_ir_frame", (0.04, 0.04, 0.045), 0.45, 0.9); panel = fl._flat("ir_ir_panel", (0.12, 0.12, 0.13), 0.4, 0.6); alu = fl._flat("ir_ir_alu", (0.75, 0.76, 0.78), 0.3, 1.0)
        scr = _emit("ir_ir_screen", (0.15, 0.7, 0.6), 2.0); led = _emit("ir_ir_led", (0.2, 1.0, 0.3), 8.0); redl = _emit("ir_ir_ledr", (1.0, 0.15, 0.1), 8.0)
        R0 = (0, 0, 0)
        W, D, H = 0.6, 0.8, 1.9
        fr = [("box", (D / 2, sy * (W / 2 - 0.02), H / 2), (D, 0.04, H), R0) for sy in (1, -1)] + [("box", (D / 2, 0, 0.04), (D, W, 0.06), R0), ("box", (D / 2, 0, H - 0.02), (D, W, 0.04), R0), ("box", (0.01, 0, H / 2), (0.02, W, H), R0)]
        panels, knobs, screens, leds, rleds = [], [], [], [], []
        z = 0.12
        while z < H - 0.2:
            h = r.choice((0.09, 0.09, 0.13, 0.18)); z += h / 2
            panels.append(("box", (D - 0.01, 0, z), (0.02, W - 0.1, h - 0.01), R0))
            if r.random() < 0.5:
                screens.append(("box", (D + 0.002, -0.1, z), (0.006, 0.2, h * 0.6), R0))
            for k in range(r.randint(2, 4)):
                knobs.append(("cyl", (D + 0.012, 0.05 + k * 0.05 + (0.08 if screens and screens[-1][1][2] == z else 0), z), (0.014, 0.014, 0.024), (0, 1.5708, 0)))
            (leds if r.random() < 0.7 else rleds).append(("cyl", (D + 0.006, 0.22, z + h / 2 - 0.025), (0.004, 0.004, 0.006), (0, 1.5708, 0)))
            z += h / 2 + 0.005
        cable = [("cyl", (0.3, W / 2 + 0.01, 0.9), (0.03, 0.03, 1.5), R0)]
        o = pa._prims(f"InstrumentRackFactory({i}).spawn_asset({i})", [(frame, fr + cable), (panel, panels), (alu, knobs), (scr, screens), (led, leds), (redl, rleds)])
        return o


class StairFlightFactory:
    """A straight stair flight with steel stringers and a metal handrail (N2 lobby refs: 'staircase with metal handrails'): 1.3 m wide (local x, back at x = 0 = the wall side) x 3.6 m long (local y) rising 2.4 m along +y;
    open treads (dark timber-look) on two steel stringers, a brushed-steel handrail on slim posts along the open (+x) side, a wall handrail on the other, a landing slab at the top."""

    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        from room_planner import proc_assets as pa
        import math as _m
        steel = fl._flat("ir_sf_steel", (0.7, 0.71, 0.73), 0.3, 1.0); tread = fl._flat("ir_sf_tread", (0.32, 0.22, 0.14), 0.5, wood=True); dark = fl._flat("ir_sf_dark", (0.06, 0.06, 0.07), 0.5)
        W, L, Hh, n = 1.3, 3.6, 2.4, 14
        run, rise = L / n, Hh / n
        R0 = (0, 0, 0)
        treads = [("box", (W / 2, -L / 2 + (k + 0.5) * run, (k + 1) * rise - 0.02), (W - 0.06, run + 0.02, 0.04), R0) for k in range(n)]
        ang = _m.atan2(Hh, L); ln = _m.hypot(L, Hh)
        stringers = [("box", (sx, 0.0, Hh / 2 - 0.1), (0.05, ln, 0.22), (ang, 0, 0)) for sx in (0.03, W - 0.03)]
        posts, rail = [], []
        for k in range(0, n, 2):
            y = -L / 2 + (k + 0.5) * run; z0 = (k + 1) * rise
            posts.append(("cyl", (W - 0.02, y, z0 + 0.45), (0.014, 0.014, 0.9), R0))
        rail.append(("cyl", (W - 0.02, 0.0, Hh / 2 + 0.95), (0.025, 0.025, ln), (-(1.5708 - ang), 0, 0)))
        wallrail = [("cyl", (0.06, 0.0, Hh / 2 + 0.9), (0.02, 0.02, ln), (-(1.5708 - ang), 0, 0))]
        landing = [("box", (W / 2, L / 2 + 0.3, Hh), (W, 0.6, 0.08), R0)]
        o = pa._prims(f"StairFlightFactory({i}).spawn_asset({i})", [(tread, treads + landing), (steel, stringers + posts + rail + wallrail)])
        return o
