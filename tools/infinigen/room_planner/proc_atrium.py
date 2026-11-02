"""Props for the building-entrance atrium lounge (atrium_lobby_01, user 2026-10-24; refs data/venue_refs/atrium_lobby_01). Front +X; free-standing pieces centred on the origin, wall pieces with their back at x = 0.

  ModularSofaFactory   a modular lounge group of 0.9 m cubic modules in dark blue-grey fabric: variant 'row' (3 modules with backs) or 'L' (a row of 3 + 2 extending forward), 0.42 m seat, 0.8 m back
  RoundStoolFactory    a drum stool 0.4 m wide, 0.42 m high, navy or brick fabric by seed
  ShellChairFactory    a bent-plywood shell lounge chair on four splayed oak legs, orange-brown leather (the wing chairs on the north side)
  BookTowerFactory     the central sculpture: a column of 24 oversized books (black / dark brown / cream), each a little rotated and offset, ~1.9 m tall; titles are bars, no readable text
  BookWallFactory      a 3.0 x 0.4 x 2.4 m oak shelving unit, 6 shelves, rows of coloured book spines
"""
from __future__ import annotations

import math
from mathutils import Vector
import random

from room_planner import proc_assets as pa

NAVY = (0.10, 0.13, 0.19)


class ModularSofaFactory:
    def __init__(self, seed):
        self.r = random.Random(seed); self.kind = self.r.choice(("row", "L", "L"))

    def spawn_asset(self, i):
        fab = pa._flat("ir_ms_fabric", NAVY, 0.9); seam = pa._flat("ir_ms_seam", (0.06, 0.08, 0.12), 0.9)
        mods = [(0.0, -0.9 + 0.9 * k, True) for k in range(3)]
        if self.kind == "L":
            mods += [(0.9, 0.9, False), (1.8, 0.9, False)]
        parts, back, seams = [], [], []
        for x, y, has_back in mods:
            parts.append(("rbox", (x, y, 0.2), (0.88, 0.88, 0.34), (0, 0, 0)))                                  # the seat base
            parts.append(("rbox", (x + 0.04, y, 0.4), (0.78, 0.8, 0.12), (0, 0, 0)))                            # a separate seat cushion on top
            if has_back:
                back.append(("rbox", (x - 0.4, y, 0.58), (0.14, 0.88, 0.36), (0, 0, 0)))                      # the back frame
                back.append(("rbox", (x - 0.31, y, 0.66), (0.12, 0.76, 0.3), (0, -0.08, 0)))                  # a loose back cushion leaning on it
            seams += [("box", (x + 0.04, y - 0.4, 0.4), (0.76, 0.005, 0.1), (0, 0, 0)), ("box", (x + 0.04, y + 0.4, 0.4), (0.76, 0.005, 0.1), (0, 0, 0))]
        sep = [("box", (x, y - 0.446, 0.3), (0.88, 0.006, 0.34), (0, 0, 0)) for x, y, _ in mods]
        return pa._prims(f"ModularSofaFactory({i}).spawn_asset({i})", [(fab, parts + back), (seam, sep + seams)])


class RoundStoolFactory:
    def __init__(self, seed):
        self.r = random.Random(seed); self.c = self.r.choice(((0.10, 0.13, 0.19), (0.10, 0.13, 0.19), (0.5, 0.22, 0.16)))

    def spawn_asset(self, i):
        fab = pa._flat("ir_rs_%d_%d" % (int(self.c[0] * 100), int(self.c[2] * 100)), self.c, 0.9)
        return pa._prims(f"RoundStoolFactory({i}).spawn_asset({i})", [(fab, [("cyl", (0, 0, 0.21), (0.2, 0.2, 0.42), (0, 0, 0)), ("cyl", (0, 0, 0.425), (0.19, 0.19, 0.02), (0, 0, 0))])])


class ShellChairFactory:
    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        lea = pa._flat("ir_sc_leather", (0.55, 0.25, 0.1), 0.55); oak = pa._flat("ir_sc_oak", (0.55, 0.4, 0.25), 0.5, wood=True)
        shell = [("rbox", (0.0, 0, 0.45), (0.55, 0.6, 0.05), (0, 0, 0)), ("rbox", (-0.22, 0, 0.7), (0.06, 0.6, 0.45), (0, -0.2, 0)),
                 ("rbox", (-0.02, 0.3, 0.55), (0.45, 0.04, 0.2), (0, 0, 0)), ("rbox", (-0.02, -0.3, 0.55), (0.45, 0.04, 0.2), (0, 0, 0))]
        legs = [("cyl", (sx * 0.2, sy * 0.2, 0.22), (0.018, 0.012, 0.44), (sy * 0.12, -sx * 0.12, 0)) for sx in (1, -1) for sy in (1, -1)]
        return pa._prims(f"ShellChairFactory({i}).spawn_asset({i})", [(lea, shell), (oak, legs)])


class BookTowerFactory:
    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        r = self.r
        cov = [pa._flat(f"ir_bt_cover_{k}", c, 0.5) for k, c in enumerate(((0.03, 0.03, 0.035), (0.1, 0.05, 0.03), (0.18, 0.1, 0.05), (0.05, 0.06, 0.07)))]
        pg = pa._flat("ir_bt_pages", (0.85, 0.8, 0.68), 0.8); bar = pa._flat("ir_bt_bar", (0.85, 0.85, 0.82), 0.6)
        g = {k: [] for k in range(4)}; pages, bars = [], []
        z = 0.02
        for n in range(24):
            h = r.uniform(0.06, 0.1); w, d = r.uniform(0.55, 0.8), r.uniform(0.4, 0.55); ox, oy = r.uniform(-0.07, 0.07), r.uniform(-0.07, 0.07); yaw = r.uniform(-0.5, 0.5)
            k = r.randrange(4); g[k].append(("box", (ox, oy, z + h / 2), (w, d, h), (0, 0, yaw)))
            pages.append(("box", (ox, oy, z + h / 2), (w - 0.02, d + 0.004, h - 0.02), (0, 0, yaw)))
            bars.append(("box", (ox + math.cos(yaw) * (w / 2 + 0.002), oy + math.sin(yaw) * (w / 2 + 0.002), z + h / 2), (0.006, d * 0.7, h * 0.22), (0, 0, yaw)))
            z += h
        return pa._prims(f"BookTowerFactory({i}).spawn_asset({i})", [(cov[k], g[k] or [("box", (0, 0, -1), (0.01, 0.01, 0.01), (0, 0, 0))]) for k in range(4)] + [(pg, pages), (bar, bars)])


class BookWallFactory:
    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        r = self.r; W, D, H = 3.0, 0.4, 2.4
        oak = pa._flat("ir_bw_oak", (0.38, 0.2, 0.1), 0.5, wood=True)
        frame = [("box", (D / 2, 0, 0.04), (D, W, 0.08), (0, 0, 0)), ("box", (D / 2, 0, H - 0.02), (D, W, 0.04), (0, 0, 0)), ("box", (0.01, 0, H / 2), (0.02, W, H), (0, 0, 0))]
        frame += [("box", (D / 2, sy * (W / 2 - 0.015), H / 2), (D, 0.03, H), (0, 0, 0)) for sy in (1, -1)] + [("box", (D / 2, 0, 0.08 + k * 0.38), (D, W, 0.025), (0, 0, 0)) for k in range(1, 6)]
        pal = ((0.7, 0.15, 0.1), (0.1, 0.25, 0.5), (0.9, 0.85, 0.7), (0.15, 0.3, 0.2), (0.08, 0.08, 0.1), (0.8, 0.55, 0.15), (0.5, 0.35, 0.25), (0.75, 0.75, 0.72))
        groups = {}
        for k in range(6):
            y = -W / 2 + 0.05; z0 = 0.095 + k * 0.38
            while y < W / 2 - 0.1:
                if r.random() < 0.08:
                    y += r.uniform(0.1, 0.3); continue
                t = r.uniform(0.02, 0.05); h = r.uniform(0.22, 0.33); c = r.choice(pal)
                groups.setdefault(c, []).append(("box", (D * 0.5, y + t / 2, z0 + h / 2), (D * 0.7, t, h), (0, 0, 0))); y += t + 0.002
        return pa._prims(f"BookWallFactory({i}).spawn_asset({i})", [(oak, frame)] + [(pa._flat(f"ir_bw_sp_{int(c[0] * 100)}_{int(c[1] * 100)}_{int(c[2] * 100)}", c, 0.6), ps) for c, ps in groups.items()])


class RoundRugFactory:
    """A round dark brown-grey wool rug 4.6 m across (the reference rug under the book tower), 1.2 cm pile with a fine ring pattern in the shader."""
    DIA = 4.6

    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        m = pa._flat("ir_rr_wool", (0.09, 0.075, 0.07), 0.95)
        return pa._prims(f"RoundRugFactory({i}).spawn_asset({i})", [(m, [("cyl", (0, 0, 0.006), (self.DIA / 2, self.DIA / 2, 0.012), (0, 0, 0))])])


class GlassBenchFactory:
    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        g = pa._flat("ir_gb_glass", (0.85, 0.93, 0.95), 0.05, transmission=0.9); st = pa._flat("ir_gb_steel", (0.7, 0.71, 0.73), 0.3, 1.0)
        return pa._prims(f"GlassBenchFactory({i}).spawn_asset({i})", [(g, [("box", (0, 0, 0.3), (0.4, 1.5, 0.08), (0, 0, 0)), ("box", (0, 0, 0.15), (0.38, 1.48, 0.3), (0, 0, 0))]), (st, [("box", (0, 0, 0.012), (0.34, 1.4, 0.024), (0, 0, 0))])])


class StoneColumnFactory:
    """A dark stone-clad pier, 0.9 x 0.9 m, full hall height (H, default 7.8 m): large panels with 1 cm joints every 1.2 m and 0.9 m."""
    H = 7.5

    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        st = pa._flat("ir_sc_stone", (0.07, 0.075, 0.08), 0.45); jt = pa._flat("ir_sc_joint", (0.02, 0.02, 0.022), 0.7)
        H = self.H
        body = [("box", (0, 0, H / 2), (0.9, 0.9, H), (0, 0, 0))]
        joints = [("box", (0, 0, z), (0.912, 0.912, 0.012), (0, 0, 0)) for z in [1.2 * k for k in range(1, int(H / 1.2))]] + [("box", (0, sy * 0.0, H / 2), (0.912, 0.012, H), (0, 0, 0)) for sy in (0,)]
        return pa._prims(f"StoneColumnFactory({i}).spawn_asset({i})", [(st, body), (jt, joints)])


class RoundPillarFactory:
    H = 7.5

    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        m = pa._flat("ir_rp_steel", (0.72, 0.73, 0.75), 0.25, 1.0)
        return pa._prims(f"RoundPillarFactory({i}).spawn_asset({i})", [(m, [("cyl", (0, 0, self.H / 2), (0.32, 0.32, self.H), (0, 0, 0))])])


class MezzanineFactory:
    """The east-side mezzanine (atrium_lobby_01): a stone-floored deck 4.0 m deep x 9 m long at z = 4.2 m (0.35 m slab with a white fascia), a glass balustrade with a stainless top rail along its front edge, a sign pedestal
    (a white box with an abstract orange block on it, no text) and two potted ficus on the deck. Back at x = 0 (the wall), front +X (towards the hall)."""
    DEPTH, LEN, Z = 4.0, 9.0, 4.2

    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        D, W, Z = self.DEPTH, self.LEN, self.Z
        stone = pa._flat("ir_mz_stone", (0.45, 0.45, 0.46), 0.5); fascia = pa._flat("ir_mz_fascia", (0.9, 0.89, 0.86), 0.6); glass = pa._flat("ir_mz_glass", (0.85, 0.93, 0.95), 0.03, transmission=0.95)
        steel = pa._flat("ir_mz_steel", (0.72, 0.73, 0.75), 0.25, 1.0); wht = pa._flat("ir_mz_pedestal", (0.93, 0.93, 0.91), 0.5); org = pa._flat("ir_mz_orange", (0.7, 0.33, 0.12), 0.35, 0.3)
        deck = [("box", (D / 2, 0, Z - 0.02), (D, W, 0.04), (0, 0, 0))]
        slab = [("box", (D / 2, 0, Z - 0.2), (D, W, 0.32), (0, 0, 0)), ("box", (D + 0.02, 0, Z - 0.22), (0.05, W, 0.45), (0, 0, 0))]
        posts = [("box", (D - 0.05, y, Z + 0.55), (0.04, 0.04, 1.1), (0, 0, 0)) for y in [-W / 2 + k * (W / 6) for k in range(7)]]
        panes = [("box", (D - 0.05, 0, Z + 0.6), (0.012, W - 0.1, 0.9), (0, 0, 0))]
        rail = [("box", (D - 0.05, 0, Z + 1.1), (0.05, W, 0.04), (0, 0, 0))]
        ped = [("box", (2.4, 1.0, Z + 0.25), (1.0, 2.0, 0.5), (0, 0, 0))]; blk = [("box", (2.4, 1.0, Z + 0.75), (0.12, 0.9, 0.5), (0, 0, 0))]
        return pa._prims(f"MezzanineFactory({i}).spawn_asset({i})", [(stone, deck), (fascia, slab), (glass, panes), (steel, posts + rail), (wht, ped), (org, blk)])


class CopperDuctFactory:
    """The curved copper-clad duct / bridge crossing the upper hall (reference upper left): a 1.3 m diameter tube, 9 m long, bent in a gentle arc in plan, with a seam ring every 1.4 m; front +X is the tube's outer side; origin at the tube start."""
    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        cu = pa._flat("ir_cd_copper", (0.66, 0.38, 0.24), 0.22, 1.0); sm = pa._flat("ir_cd_seam", (0.42, 0.24, 0.15), 0.4, 1.0)
        import bmesh
        import bpy
        R, ang, rad, NS, NR = 14.0, 9.0 / 14.0, 0.45, 96, 40                    # one smooth torus section (no per-segment bevels: those read as ribs), 3 thin seam bands
        bm = bmesh.new()

        def ring(a, r, slot, ring_z=0.0):
            p = Vector((R * math.sin(a), R * (1 - math.cos(a)), 0.0)); nv = Vector((-math.sin(a), math.cos(a), 0.0))
            return [bm.verts.new(p + r * (math.cos(2 * math.pi * q / NR) * nv + math.sin(2 * math.pi * q / NR) * Vector((0, 0, 1)))) for q in range(NR)]

        def sweep(a0, a1, r, slot, steps):
            prev = ring(a0, r, slot)
            for k in range(1, steps + 1):
                cur = ring(a0 + (a1 - a0) * k / steps, r, slot)
                for q in range(NR):
                    f = bm.faces.new((prev[q], prev[(q + 1) % NR], cur[(q + 1) % NR], cur[q])); f.material_index = slot; f.smooth = True
                prev = cur
        sweep(0.0, ang, rad, 0, NS)
        for fr in (0.2, 0.5, 0.8):                                               # seam bands: 3 cm wide, 6 mm proud
            sweep(ang * fr, ang * fr + 0.03 / R, rad + 0.006, 1, 2)
        me = bpy.data.meshes.new("CopperDuct"); bm.to_mesh(me); bm.free()
        me.materials.append(cu); me.materials.append(sm)
        o = bpy.data.objects.new(f"CopperDuctFactory({i}).spawn_asset({i})", me); bpy.context.scene.collection.objects.link(o)
        return o
