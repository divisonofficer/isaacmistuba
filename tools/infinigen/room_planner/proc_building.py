"""Shared building-interior props for the university-building scenes (lounge S29, cafeteria S27, parking S28, office floor O). Factory-shaped, front +X, back at x = 0 for wall pieces.

  ExitSignFactory            a green emissive exit / arrow sign (0.04 x 0.32 x 0.16 m, origin at its centre) with a white pictogram block
  ElevatorDoorFactory        a flush stainless double elevator door (0.08 x 1.15 x 2.1 m, origin at the floor) with a floor indicator above and a call panel beside
  RoundAmberPendantFactory   a round pendant: cord from the ceiling (origin at the lamp body, cord 0.9 m up), amber-white emissive disc and a small point light
  DiamondPendantFactory      a faceted diamond-shaped pendant (cafeteria ref): origin at the body, cord 1.0 m up, warm amber emissive
"""
from __future__ import annotations

import math
import random

import bpy

from room_planner import proc_assets as pa
from room_planner import proc_boutique_flagship as fl
from room_planner.proc_boutique_flagship import mesh_object


def _emit(name, rgb, strength):
    m = pa._flat(name, rgb, 0.3)
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Emission Color"].default_value = (*rgb, 1.0); b.inputs["Emission Strength"].default_value = strength
    return m


class ExitSignFactory:
    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        g = _emit("ir_exit_green", (0.1, 0.8, 0.35), 6.0); wh = _emit("ir_exit_white", (0.95, 0.98, 0.95), 7.0); blk = pa._flat("ir_exit_housing", (0.12, 0.12, 0.13), 0.5)
        return mesh_object(f"ExitSignFactory({i}).spawn_asset({i})",
                           [(blk, [("box", -0.005, 0, 0, 0.03, 0.34, 0.18)]), (g, [("box", 0.012, 0, 0, 0.008, 0.31, 0.15)]), (wh, [("box", 0.018, -0.07, 0, 0.006, 0.07, 0.1), ("box", 0.018, 0.06, 0, 0.006, 0.1, 0.03)])],
                           bevel=False)


class ElevatorDoorFactory:
    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        steel = pa._flat("ir_elev_steel", (0.62, 0.63, 0.65), 0.3, 1.0); frame = pa._flat("ir_elev_frame", (0.5, 0.5, 0.52), 0.35, 0.9); disp = _emit("ir_elev_disp", (1.0, 0.45, 0.2), 3.0)
        dk = pa._flat("ir_elev_dark", (0.05, 0.05, 0.06), 0.4, 0.4)
        W, H = 1.15, 2.1
        return mesh_object(f"ElevatorDoorFactory({i}).spawn_asset({i})",
                           [(frame, [("box", 0.03, -W / 2 - 0.03, H / 2 + 0.05, 0.06, 0.06, H + 0.1), ("box", 0.03, W / 2 + 0.03, H / 2 + 0.05, 0.06, 0.06, H + 0.1), ("box", 0.03, 0, H + 0.08, 0.06, W + 0.12, 0.06)]),
                            (steel, [("box", 0.03, -W / 4 - 0.005, H / 2, 0.04, W / 2 - 0.01, H), ("box", 0.03, W / 4 + 0.005, H / 2, 0.04, W / 2 - 0.01, H)]),
                            (dk, [("box", 0.04, 0, H / 2, 0.02, 0.012, H), ("box", 0.04, 0, H + 0.22, 0.03, 0.22, 0.1), ("box", 0.04, W / 2 + 0.28, 1.1, 0.02, 0.1, 0.18)]),
                            (disp, [("box", 0.056, 0, H + 0.22, 0.004, 0.05, 0.05), ("box", 0.056, W / 2 + 0.28, 1.12, 0.004, 0.03, 0.03)])], bevel=False)


class RoundAmberPendantFactory:
    def __init__(self, seed):
        self.r = random.Random(seed); self.rad = self.r.choice((0.15, 0.18, 0.22))

    def spawn_asset(self, i):
        rad = self.rad
        cord = pa._flat("ir_pend_cord", (0.05, 0.05, 0.05), 0.5); glow = _emit("ir_pend_amber", (1.0, 0.82, 0.55), 9.0); hood = pa._flat("ir_pend_hood", (0.9, 0.88, 0.82), 0.4)
        o = mesh_object(f"RoundAmberPendantFactory({i}).spawn_asset({i})",
                        [(cord, [("cyl", (0, 0, 0.05), (0, 0, 0.95), 0.004, 6)]), (hood, [("cyl", (0, 0, 0.02), (0, 0, 0.1), rad * 1.05, 24)]), (glow, [("cyl", (0, 0, -0.005), (0, 0, 0.02), rad * 0.95, 24)])], bevel=False)
        ld = bpy.data.lights.new(f"ir_pend_{i}", "POINT"); ld.energy = 25.0; ld.color = (1.0, 0.78, 0.5); ld.shadow_soft_size = 0.1
        lo = bpy.data.objects.new(f"PointLampFactory(pend).spawn_asset({i})", ld); bpy.context.scene.collection.objects.link(lo); lo.parent = o; lo.location = (0, 0, -0.12)
        return o


class DiamondPendantFactory:
    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        glow = _emit("ir_diam_amber", (1.0, 0.7, 0.35), 8.0); cord = pa._flat("ir_pend_cord", (0.05, 0.05, 0.05), 0.5)
        import bmesh
        bm = bmesh.new()
        r = bmesh.ops.create_cone(bm, cap_ends=True, segments=4, radius1=0.17, radius2=0.0, depth=0.12); bmesh.ops.translate(bm, vec=(0, 0, -0.06), verts=r["verts"])
        r2 = bmesh.ops.create_cone(bm, cap_ends=True, segments=4, radius1=0.0, radius2=0.17, depth=0.1); bmesh.ops.translate(bm, vec=(0, 0, 0.05), verts=r2["verts"])
        me = bpy.data.meshes.new("diamond"); bm.to_mesh(me); bm.free(); me.materials.append(glow)
        o = bpy.data.objects.new(f"DiamondPendantFactory({i}).spawn_asset({i})", me); bpy.context.scene.collection.objects.link(o)
        c = mesh_object(f"cord_{i}", [(cord, [("cyl", (0, 0, 0.1), (0, 0, 1.0), 0.004, 6)])], bevel=False)
        c.parent = o
        ld = bpy.data.lights.new(f"ir_diam_{i}", "POINT"); ld.energy = 22.0; ld.color = (1.0, 0.72, 0.4); ld.shadow_soft_size = 0.08
        lo = bpy.data.objects.new(f"PointLampFactory(diam).spawn_asset({i})", ld); bpy.context.scene.collection.objects.link(lo); lo.parent = o; lo.location = (0, 0, -0.1)
        return o
