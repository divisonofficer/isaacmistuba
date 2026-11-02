"""Props for the science-museum scene (reference set space_museum_01; docs/space_museum_design_proposal.md). Flag ROOM_MUSEUM=1.

Factory-shaped like proc_assets (Cls(seed).spawn_asset(i), front +X, origin at the bottom centre unless noted); one merged mesh per object:

  ElementWallFactory      a periodic-table wall: black panel with ~118 grey box showcases whose back faces glow blue / yellow / orange / white (front +X, back at x = 0)
  MarbleBenchFactory      a cream marble bench 1.6 x 0.45 x 0.45 m on three round columns
  RotundaRailFactory      a ring parapet of marble blocks round a circular floor opening (origin at the ring centre, bottom at floor level, R = 1.9 m)
  PendulumFactory         a long wire and a brass bob hung from z = 0 down (origin at the ceiling, hangs L = 6 m)
  GlowRingFactory         a ring of 60 emissive blocks (the pendulum pit's lit scale) at R = 1.5 m, origin at its centre
  PictureFrameLitFactory  a dark framed emissive picture with a text plaque (front +X, back at x = 0); `kind` nebula_blue / nebula_ring / earth_limb
  NebulaWallPanelFactory  a full-wall emissive nebula panel 3.2 x 2.1 m (back at x = 0)
"""
from __future__ import annotations

import math
import random
from pathlib import Path

import bmesh
import bpy

from room_planner import proc_boutique_flagship as fl
from room_planner.proc_boutique_flagship import mesh_object

ART = Path("/jarvis/project/robomituba/data/venue_refs/museum_art")


def _emit(name, rgb, strength):
    m = bpy.data.materials.get(name)
    if m is not None:
        return m
    m = bpy.data.materials.new(name); m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*rgb, 1); b.inputs["Roughness"].default_value = 0.5
    b.inputs["Emission Color"].default_value = (*rgb, 1); b.inputs["Emission Strength"].default_value = strength
    return m


def _image_emit(name, file, strength):
    m = bpy.data.materials.get(name)
    if m is not None:
        return m
    m = bpy.data.materials.new(name); m.use_nodes = True
    nt = m.node_tree; b = nt.nodes["Principled BSDF"]
    t = nt.nodes.new("ShaderNodeTexImage"); t.image = bpy.data.images.load(str(ART / file), check_existing=True)
    nt.links.new(t.outputs["Color"], b.inputs["Base Color"]); nt.links.new(t.outputs["Color"], b.inputs["Emission Color"])
    b.inputs["Emission Strength"].default_value = strength; b.inputs["Roughness"].default_value = 0.4
    return m


#: the periodic table as (period, group) cells: 118 elements, the f-block as two rows below
def _table_cells():
    cells = []
    for p, groups in ((1, (1, 18)), (2, tuple(range(1, 3)) + tuple(range(13, 19))), (3, tuple(range(1, 3)) + tuple(range(13, 19)))):
        cells += [(p, g) for g in groups]
    for p in (4, 5):
        cells += [(p, g) for g in range(1, 19)]
    for p in (6, 7):
        cells += [(p, g) for g in range(1, 19) if g != 3]                  # group 3 holds the f-block marker, not shown separately
    cells += [(8.5, 3 + k) for k in range(14)] + [(9.5, 3 + k) for k in range(14)]
    return cells


class ElementWallFactory:
    def __init__(self, seed):
        self.seed = seed

    def spawn_asset(self, i):
        r = random.Random(self.seed * 7 + i); pitch, size = 0.27, 0.23
        panel = fl._flat("ir_mu_panel", (0.03, 0.035, 0.04), 0.6)
        frame = fl._flat("ir_mu_showcase_grey", (0.42, 0.43, 0.45), 0.5, 0.3)
        glow = {"blue": _emit("ir_mu_glow_blue", (0.2, 0.45, 1.0), 4.0), "yellow": _emit("ir_mu_glow_yellow", (1.0, 0.8, 0.15), 3.5),
                "orange": _emit("ir_mu_glow_orange", (1.0, 0.45, 0.12), 3.5), "white": _emit("ir_mu_glow_white", (0.85, 0.92, 1.0), 3.5), "dim": _emit("ir_mu_glow_dim", (0.2, 0.2, 0.22), 1.0)}
        cells = _table_cells(); frames, glows, panel_parts = [], {k: [] for k in glow}, []
        gx = -9 * pitch                                                         # centre the 18 columns on y = 0
        zc = 0.3 + 9.2 * pitch
        for p, g in cells:
            y = gx + (g - 0.5) * pitch; z = zc - (p - 0.5) * pitch
            t = 0.12                                                            # showcase depth
            for dy, dz, sy, sz in ((-size / 2 + 0.01, 0, 0.02, size), (size / 2 - 0.01, 0, 0.02, size), (0, size / 2 - 0.01, size, 0.02), (0, -size / 2 + 0.01, size, 0.02)):
                frames.append(("box", 0.1 + t / 2, y + dy, z + dz, t, sy, sz))
            k = r.choices(("blue", "yellow", "orange", "white", "dim"), (50, 14, 14, 14, 8))[0]
            glows[k].append(("box", 0.1 + 0.01, y, z, 0.01, size - 0.03, size - 0.03))
        panel_parts.append(("box", 0.04, 0, zc - 4.2 * pitch, 0.08, 18.4 * pitch, 10.3 * pitch))
        groups = [(panel, panel_parts), (frame, frames)] + [(glow[k], v) for k, v in glows.items() if v]
        return mesh_object(f"ElementWallFactory({self.seed}).spawn_asset({i})", groups, bevel=False)


class MarbleBenchFactory:
    def __init__(self, seed):
        self.seed = seed

    def spawn_asset(self, i):
        marble = fl._flat("ir_mu_marble_cream", (0.85, 0.8, 0.7), 0.25); col = fl._flat("ir_mu_column_stone", (0.78, 0.72, 0.6), 0.5)
        L, D = 1.6, 0.45
        cols = [("cyl", (0, y, 0.0), (0, y, 0.4), 0.07, 14) for y in (-L / 2 + 0.2, 0.0, L / 2 - 0.2)] + [("cyl", (0, y, 0.0), (0, y, 0.04), 0.1, 14) for y in (-L / 2 + 0.2, 0.0, L / 2 - 0.2)]
        return mesh_object(f"MarbleBenchFactory({self.seed}).spawn_asset({i})", [(col, cols), (marble, [("box", 0, 0, 0.42, D, L, 0.08)])], bevel=False)


class RotundaRailFactory:
    """A low, wide marble FOUNTAIN RIM round the circular floor opening (R = 1.9 m): a 0.5 m high x 0.55 m wide ring of marble blocks with a gilded cap, eight slim brass stanchions
    with a thin brass rail above it, and a dark reflective water disc inside (the lit scale ring sits on it). Origin at the ring centre, bottom at floor level. (S25 A/B: 'a low wide
    marble fountain rim', then 'brass railing': both, the rim carrying a light rail.)"""
    def __init__(self, seed):
        self.seed = seed

    def spawn_asset(self, i):
        stone = fl._flat("ir_mu_parapet", (0.72, 0.62, 0.45), 0.4); gold = fl._flat("ir_mu_brass_rail", (0.55, 0.42, 0.22), 0.4, 1.0)
        water = fl._flat("ir_mu_water", (0.02, 0.09, 0.11), 0.03, 0.9)
        n, R = 32, 1.9; rim, caps, brass = [], [], []
        for k in range(n):
            a = 2 * math.pi * k / n; w = 2 * math.pi * R / n * 1.03
            rim.append(("box", R * math.cos(a), R * math.sin(a), 0.25, 0.55, w, 0.5, a + math.pi / 2))
            caps.append(("box", R * math.cos(a), R * math.sin(a), 0.52, 0.6, w, 0.04, a + math.pi / 2))
            brass.append(("cyl", (R * math.cos(a), R * math.sin(a), 0.98), (R * math.cos(a + 2 * math.pi / n), R * math.sin(a + 2 * math.pi / n), 0.98), 0.018, 6))   # the thin rail
        for k in range(8):
            a = 2 * math.pi * k / 8
            brass.append(("cyl", (R * math.cos(a), R * math.sin(a), 0.52), (R * math.cos(a), R * math.sin(a), 1.0), 0.02, 8))
        return mesh_object(f"RotundaRailFactory({self.seed}).spawn_asset({i})",
                           [(stone, rim), (stone, caps), (gold, brass), (water, [("cyl", (0, 0, 0.0), (0, 0, 0.03), 1.3, 40)])], bevel=False)


class PendulumFactory:
    L = 6.0

    def __init__(self, seed):
        self.seed = seed

    def spawn_asset(self, i):
        wire = fl._flat("ir_mu_wire", (0.1, 0.1, 0.1), 0.4, 0.8); brass = fl._flat("ir_mu_brass", (0.85, 0.65, 0.25), 0.2, 1.0)
        return mesh_object(f"PendulumFactory({self.seed}).spawn_asset({i})", [(wire, [("cyl", (0, 0, 0), (0, 0, -self.L + 0.2), 0.002, 4)]), (brass, [("sph", (0, 0, -self.L), 0.16, 3), ("cyl", (0, 0, -self.L + 0.15), (0, 0, -self.L + 0.4), 0.02, 6)])], bevel=False)


class GlowRingFactory:
    """The lit scale ring of the pendulum pit: 60 emissive blocks on a dark ring bed (origin at the centre, top at z = 0)."""
    def __init__(self, seed):
        self.seed = seed

    def spawn_asset(self, i):
        glow = _emit("ir_mu_ring_glow", (1.0, 0.8, 0.45), 9.0); bed = fl._flat("ir_mu_ring_bed", (0.12, 0.1, 0.07), 0.4, 0.6)
        n, R = 60, 1.5
        blocks = [("box", R * math.cos(2 * math.pi * k / n), R * math.sin(2 * math.pi * k / n), -0.01, 0.16, 2 * math.pi * R / n * 0.9, 0.02, 2 * math.pi * k / n + math.pi / 2) for k in range(n)]
        bed_p = [("box", (R + 0.12) * math.cos(2 * math.pi * k / 40), (R + 0.12) * math.sin(2 * math.pi * k / 40), -0.03, 0.4, 2 * math.pi * R / 40 * 1.05, 0.02, 2 * math.pi * k / 40 + math.pi / 2) for k in range(40)]
        return mesh_object(f"GlowRingFactory({self.seed}).spawn_asset({i})", [(bed, bed_p), (glow, blocks)], bevel=False)


class PictureFrameLitFactory:
    KINDS = {"nebula_blue": ("nebula_blue.png", 0.55, 0.7), "nebula_ring": ("nebula_ring.png", 0.55, 0.7), "earth_limb": ("earth_limb.png", 1.0, 0.57)}

    def __init__(self, seed, kind=None):
        self.kind = kind or random.Random(seed).choice(tuple(self.KINDS)); self.seed = seed

    def spawn_asset(self, i):
        f, w, h = self.KINDS[self.kind]
        frame = fl._flat("ir_mu_frame_dark", (0.05, 0.04, 0.035), 0.5); plaque = fl._flat("ir_mu_plaque", (0.1, 0.09, 0.07), 0.3, 0.9)
        img = _image_emit(f"ir_mu_pic_{self.kind}", f, 3.0)
        o = mesh_object(f"PictureFrameLitFactory({self.seed}).spawn_asset({i})", [
            (frame, [("box", 0.03, 0, h / 2 + 0.05, 0.06, w + 0.1, h + 0.1)]), (plaque, [("box", 0.03, 0, -0.02, 0.02, 0.18, 0.05)]),
            (img, [("box", 0.062, 0, h / 2 + 0.05, 0.004, w, h)])], bevel=False)
        return o


class NebulaWallPanelFactory:
    def __init__(self, seed):
        self.seed = seed

    def spawn_asset(self, i):
        img = _image_emit("ir_mu_nebula_wall", "nebula_red.png", 2.5); edge = fl._flat("ir_mu_panel_edge", (0.04, 0.04, 0.045), 0.5)
        return mesh_object(f"NebulaWallPanelFactory({self.seed}).spawn_asset({i})", [(edge, [("box", 0.03, 0, 1.15, 0.06, 3.3, 2.2)]), (img, [("box", 0.062, 0, 1.15, 0.004, 3.2, 2.1)])], bevel=False)


class PictureFrameNebulaBlueFactory(PictureFrameLitFactory):
    def __init__(self, seed):
        super().__init__(seed, "nebula_blue")


class PictureFrameNebulaRingFactory(PictureFrameLitFactory):
    def __init__(self, seed):
        super().__init__(seed, "nebula_ring")


class PictureFrameEarthFactory(PictureFrameLitFactory):
    def __init__(self, seed):
        super().__init__(seed, "earth_limb")
