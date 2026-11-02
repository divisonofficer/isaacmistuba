"""Furniture and fixtures for the rooftop fine-dining restaurant (reference set rooftop_restaurant_01; docs/rooftop_fine_dining_design_proposal.md).

Factory-shaped like proc_assets (Cls(seed).spawn_asset(i), front +X, origin at the bottom centre; wall / column pieces have their back at x = 0 where noted).
All geometry is boxes / cylinders merged into one mesh per object (proc_boutique_flagship.mesh_object); materials are Principled.

  VelvetBoothFactory       navy channel-tufted booth (2.2 x 0.8 x 1.05 m), front +X
  BarStoolFactory          high bar stool; style white perforated metal or gold chrome with a tufted grey seat (0.45 x 0.45 x 1.0 m seat 0.75)
  BlackMarbleTableFactory  black-veined marble top on a thin galvanised steel frame; low 1.2 x 0.7 x 0.75 / high 0.7 x 0.7 x 1.05 / round high
  CubeOttomanFactory       cream leather cube 0.5 x 0.5 x 0.45
  MirrorColumnFactory      stone-clad column 0.7 x 0.7 x 3.2 m with a framed mirror panel on the +X face (centre origin, bottom at 0)
  GlassBalustradeFactory   glass panel 2.4 m with a steel handrail, back at x = 0 (stands on the edge of the raised platform)
  FloorAcFactory           white cabinet air conditioner 0.5 x 0.35 x 1.9 m with a vent grille, back at x = 0
  PatioHeaterFactory       pyramid patio heater: steel frame, glass tube, 2.2 m
  FineDiningSettingFactory a plate, napkin, knife and fork, a tumbler and a stem glass (placed on a table by the caller), 0.45 x 0.35 m
"""
from __future__ import annotations

import math
import random

import bpy

from room_planner import proc_boutique_flagship as fl
from room_planner.proc_boutique_flagship import mesh_object


def _marble_black(name="ir_marble_black"):
    m = bpy.data.materials.get(name)
    if m is not None:
        return m
    m = bpy.data.materials.new(name); m.use_nodes = True
    nt = m.node_tree; N, L = nt.nodes, nt.links; b = N["Principled BSDF"]
    tc = N.new("ShaderNodeTexCoord"); mp = N.new("ShaderNodeMapping"); mp.inputs["Scale"].default_value = (2.2, 2.2, 2.2)
    L.new(tc.outputs["Object"], mp.inputs["Vector"])
    nz = N.new("ShaderNodeTexNoise"); nz.inputs["Scale"].default_value = 1.6; nz.inputs["Detail"].default_value = 8; nz.inputs["Distortion"].default_value = 1.4
    L.new(mp.outputs["Vector"], nz.inputs["Vector"])
    # thin veins: |noise - 0.5| small -> light line; a second, larger noise decides where veins show at all
    vn = N.new("ShaderNodeTexNoise"); vn.inputs["Scale"].default_value = 2.4; vn.inputs["Detail"].default_value = 9; vn.inputs["Distortion"].default_value = 1.2
    L.new(mp.outputs["Vector"], vn.inputs["Vector"])
    ab = N.new("ShaderNodeMath"); ab.operation = "SUBTRACT"; ab.inputs[1].default_value = 0.5; L.new(vn.outputs["Fac"], ab.inputs[0])
    ab2 = N.new("ShaderNodeMath"); ab2.operation = "ABSOLUTE"; L.new(ab.outputs["Value"], ab2.inputs[0])
    rp = N.new("ShaderNodeValToRGB"); rp.color_ramp.elements[0].position = 0.0; rp.color_ramp.elements[1].position = 0.03
    rp.color_ramp.elements[0].color = (0.7, 0.7, 0.68, 1); rp.color_ramp.elements[1].color = (0.014, 0.014, 0.017, 1)
    L.new(ab2.outputs["Value"], rp.inputs["Fac"])
    gate = N.new("ShaderNodeValToRGB"); gate.color_ramp.elements[0].position = 0.42; gate.color_ramp.elements[1].position = 0.62
    gate.color_ramp.elements[0].color = (0, 0, 0, 1); gate.color_ramp.elements[1].color = (1, 1, 1, 1); L.new(nz.outputs["Fac"], gate.inputs["Fac"])
    mix = N.new("ShaderNodeMix"); mix.data_type = "RGBA"; mix.blend_type = "MIX"
    mix.inputs[6].default_value = (0.014, 0.014, 0.017, 1); L.new(rp.outputs["Color"], mix.inputs[7]); L.new(gate.outputs["Color"], mix.inputs["Factor"])
    L.new(mix.outputs[2], b.inputs["Base Color"])
    rr = N.new("ShaderNodeMath"); rr.operation = "MULTIPLY_ADD"; rr.inputs[1].default_value = 0.06; rr.inputs[2].default_value = 0.05
    L.new(nz.outputs["Fac"], rr.inputs[0]); L.new(rr.outputs["Value"], b.inputs["Roughness"])
    b.inputs["Coat Weight"].default_value = 0.4; b.inputs["Coat Roughness"].default_value = 0.05
    return m


def _steel(name="ir_gal_steel", rgb=(0.55, 0.56, 0.58)):
    return fl._flat(name, rgb, 0.4, 1.0)


class VelvetBoothFactory:
    """Navy channel-tufted booth (front +X, the seating side): seat 2.2 x 0.5 x 0.45, tall back 1.05 m with 9 vertical channels."""
    def __init__(self, seed):
        r = random.Random(seed); self.L = r.choice((1.8, 2.2, 2.6)); self.seed = seed
        self.c = r.choice(((0.03, 0.035, 0.11), (0.025, 0.03, 0.09), (0.05, 0.05, 0.06)))

    def spawn_asset(self, i):
        v = fl._flat(f"ir_velvet_{int(self.c[2] * 100)}", self.c, 0.85)
        wood = fl._flat("ir_booth_base", (0.12, 0.1, 0.09), 0.5)
        L, D = self.L, 0.8
        ch = max(6, int(L / 0.24)); pitch = (L - 0.1) / ch
        back = [("box", -D / 2 + 0.16, -L / 2 + 0.05 + (k + 0.5) * pitch, 0.5 + 0.2, 0.14 if k % 2 == 0 else 0.11, pitch * 0.92, 0.6) for k in range(ch)]
        parts = [("box", -D / 2 + 0.2, 0, 0.45 / 2 + 0.06, 0.55, L, 0.45), ("box", -D / 2 + 0.16, 0, 0.99, 0.12, L, 0.12)] + back
        return mesh_object(f"VelvetBoothFactory({self.seed}).spawn_asset({i})",
                           [(v, parts), (wood, [("box", -D / 2 + 0.2, 0, 0.03, 0.6, L + 0.02, 0.06)])])


class BarStoolFactory:
    """High bar stool (front +X): `white` perforated-metal frame with a grey tufted seat, or `gold` mirrored chrome."""
    def __init__(self, seed, style=None):
        r = random.Random(seed); self.style = style or r.choice(("white", "gold")); self.seed = seed

    def spawn_asset(self, i):
        gold = self.style == "gold"
        frame = fl._flat("ir_stool_gold" if gold else "ir_stool_white", (0.85, 0.65, 0.25) if gold else (0.93, 0.93, 0.92), 0.15 if gold else 0.45, 1.0 if gold else 0.2)
        seat = fl._flat("ir_stool_seat_grey", (0.38, 0.38, 0.4), 0.85)
        parts = []
        for sx in (1, -1):
            for sy in (1, -1):
                parts.append(("cyl", (sx * 0.19, sy * 0.19, 0.0), (sx * 0.15, sy * 0.15, 0.74), 0.012, 8))
        parts += [("cyl", (0.17, 0.17, 0.3), (0.17, -0.17, 0.3), 0.01, 8), ("cyl", (-0.17, 0.17, 0.3), (-0.17, -0.17, 0.3), 0.01, 8)]
        back = [("box", -0.2, 0, 0.9, 0.02, 0.34, 0.26)] if gold else [("box", -0.2, 0, 0.88, 0.02, 0.38, 0.3)]
        return mesh_object(f"BarStoolFactory({self.seed}).spawn_asset({i})", [(frame, parts + back), (seat, [("box", 0, 0, 0.77, 0.4, 0.4, 0.07)])])


class BlackMarbleTableFactory:
    """Black-veined marble table on a thin galvanised frame (front +X). kinds: low (1.2 x 0.7 x 0.75), high (0.7 x 0.7 x 1.05), round (0.7 dia, 1.05)."""
    def __init__(self, seed, kind=None):
        r = random.Random(seed); self.kind = kind or r.choice(("low", "low", "high", "round")); self.seed = seed

    def spawn_asset(self, i):
        top, steel = _marble_black(), _steel()
        if self.kind == "low":
            w, d, h = 1.2, 0.7, 0.75
        else:
            w, d, h = 0.7, 0.7, 1.05
        t = 0.03
        legs = [("box", sx * (d / 2 - 0.03), sy * (w / 2 - 0.03), (h - t) / 2, 0.035, 0.035, h - t) for sx in (1, -1) for sy in (1, -1)]
        rails = [("box", sx * (d / 2 - 0.03), 0, h - t - 0.03, 0.03, w - 0.04, 0.05) for sx in (1, -1)] + [("box", 0, sy * (w / 2 - 0.03), h - t - 0.03, d - 0.04, 0.03, 0.05) for sy in (1, -1)]
        if self.kind == "round":
            parts = [("cyl", (0, 0, 0.0), (0, 0, h - t), 0.025, 10), ("cyl", (0, 0, 0.012), (0, 0, 0.02), 0.22, 16)]
            tops = [("cyl", (0, 0, h - t), (0, 0, h), 0.35, 24)]
        else:
            parts, tops = legs + rails, [("box", 0, 0, h - t / 2, d, w, t)]
        return mesh_object(f"BlackMarbleTableFactory({self.seed}).spawn_asset({i})", [(steel, parts), (top, tops)], bevel=False)


class CubeOttomanFactory:
    def __init__(self, seed):
        self.seed = seed

    def spawn_asset(self, i):
        leather = fl._flat("ir_cream_leather", (0.86, 0.83, 0.72), 0.45)
        return mesh_object(f"CubeOttomanFactory({self.seed}).spawn_asset({i})", [(leather, [("box", 0, 0, 0.225, 0.5, 0.5, 0.45)])])


class MirrorColumnFactory:
    """Stone-clad column with a framed mirror on the +X face (origin centre, bottom at 0)."""
    def __init__(self, seed):
        self.seed = seed

    def spawn_asset(self, i):
        stone = fl._flat("ir_col_stone", (0.62, 0.58, 0.5), 0.6)
        mirror = fl._flat("ir_col_mirror", (0.95, 0.95, 0.95), 0.02, 1.0)
        frame = fl._flat("ir_col_frame", (0.8, 0.62, 0.28), 0.25, 1.0)
        H = 3.2
        return mesh_object(f"MirrorColumnFactory({self.seed}).spawn_asset({i})", [
            (stone, [("box", 0, 0, H / 2, 0.7, 0.7, H)]), (mirror, [("box", 0.352, 0, H / 2 - 0.1, 0.01, 0.4, 2.5)]),
            (frame, [("box", 0.356, 0, 0.15 + 0.1, 0.014, 0.46, 0.05), ("box", 0.356, 0, H - 0.4, 0.014, 0.46, 0.05), ("box", 0.356, 0.215, H / 2 - 0.1, 0.014, 0.05, 2.5), ("box", 0.356, -0.215, H / 2 - 0.1, 0.014, 0.05, 2.5)])])


class GlassBalustradeFactory:
    """Glass panel with a steel handrail (back at x = 0, front +X toward the lower floor), 2.4 m long, 1.0 m high."""
    def __init__(self, seed):
        self.seed = seed

    def spawn_asset(self, i):
        glass = bpy.data.materials.get("ir_balustrade_glass")
        if glass is None:
            glass = bpy.data.materials.new("ir_balustrade_glass"); glass.use_nodes = True
            b = glass.node_tree.nodes["Principled BSDF"]
            b.inputs["Base Color"].default_value = (0.9, 0.97, 1.0, 1); b.inputs["Roughness"].default_value = 0.0
            b.inputs["Transmission Weight"].default_value = 1.0; b.inputs["IOR"].default_value = 1.45
            from room_planner.rooftop_shell import shadow_pass
            shadow_pass(glass)
        steel = _steel("ir_rail_chrome", (0.8, 0.8, 0.82))
        L = 2.4
        rail = [("cyl", (0.0, -L / 2, 1.02), (0.0, L / 2, 1.02), 0.022, 10), ("cyl", (0.0, -L / 2, 0.04), (0.0, L / 2, 0.04), 0.012, 8)]
        posts = [("cyl", (0.0, y, 0.0), (0.0, y, 1.02), 0.014, 8) for y in (-L / 2 + 0.03, L / 2 - 0.03)]
        o = mesh_object(f"GlassBalustradeFactory({self.seed}).spawn_asset({i})", [(steel, rail + posts), (glass, [("box", 0, 0, 0.53, 0.012, L - 0.1, 0.9)])], bevel=False)
        return o


class FloorAcFactory:
    """White floor-standing air conditioner (back at x = 0, front +X)."""
    def __init__(self, seed):
        self.seed = seed

    def spawn_asset(self, i):
        white = fl._flat("ir_ac_cabinet_white", (0.9, 0.9, 0.88), 0.45)
        dark = fl._flat("ir_ac_vent_dark", (0.06, 0.06, 0.07), 0.5)
        louvers = [("box", 0.176, 0, 1.45 + 0.04 * k, 0.006, 0.36, 0.012) for k in range(8)] + [("box", 0.176, 0, 0.25 + 0.04 * k, 0.006, 0.36, 0.012) for k in range(5)]
        return mesh_object(f"FloorAcFactory({self.seed}).spawn_asset({i})", [(white, [("box", 0.175, 0, 0.95, 0.35, 0.5, 1.9)]), (dark, louvers)])


class PatioHeaterFactory:
    """Pyramid patio heater (front +X irrelevant): steel base and pyramid frame, a glass tube, a top reflector; 2.2 m."""
    def __init__(self, seed):
        self.seed = seed

    def spawn_asset(self, i):
        steel = _steel("ir_heater_steel", (0.2, 0.2, 0.21))
        glass = fl._flat("ir_heater_glass", (0.9, 0.95, 1.0), 0.05)
        corners = [(sx * 0.25, sy * 0.25) for sx in (1, -1) for sy in (1, -1)]
        frame = [("cyl", (cx, cy, 0.1), (cx * 0.35, cy * 0.35, 1.95), 0.012, 6) for cx, cy in corners]
        frame += [("box", 0, 0, 0.04, 0.6, 0.6, 0.08), ("cyl", (0, 0, 1.95), (0, 0, 2.05), 0.1, 12), ("cyl", (0, 0, 2.05), (0, 0, 2.1), 0.32, 16)]
        return mesh_object(f"PatioHeaterFactory({self.seed}).spawn_asset({i})", [(steel, frame), (glass, [("cyl", (0, 0, 0.3), (0, 0, 1.9), 0.05, 12)])], bevel=False)


class FineDiningSettingFactory:
    """A table setting for one (front +X toward the diner): a white rimmed plate, a napkin, knife and fork, a tumbler and a stem glass."""
    def __init__(self, seed):
        self.seed = seed

    def spawn_asset(self, i):
        r = random.Random(self.seed * 3 + i)
        plate = fl._flat("ir_fd_plate", (0.94, 0.94, 0.92), 0.2)
        napkin = fl._flat("ir_fd_napkin", (0.95, 0.95, 0.93), 0.9)
        steel = _steel("ir_fd_cutlery", (0.8, 0.8, 0.82))
        glass = bpy.data.materials.get("ir_fd_glass")
        if glass is None:
            glass = bpy.data.materials.new("ir_fd_glass"); glass.use_nodes = True
            b = glass.node_tree.nodes["Principled BSDF"]; b.inputs["Roughness"].default_value = 0.02; b.inputs["Transmission Weight"].default_value = 1.0
        diner = [("cyl", (0, 0, 0.0), (0, 0, 0.018), 0.13, 20), ("cyl", (0, 0, 0.018), (0, 0, 0.026), 0.085, 20)]
        nap = [("box", 0.0, -0.22, 0.01, 0.12, 0.16, 0.02, r.uniform(-0.1, 0.1))]
        cut = [("box", 0.0, 0.18, 0.004, 0.2, 0.012, 0.006), ("box", 0.0, 0.2, 0.004, 0.18, 0.02, 0.006)]
        glasses = [("cyl", (0.15, -0.16, 0.0), (0.15, -0.16, 0.09), 0.032, 14), ("cyl", (0.18, 0.1, 0.0), (0.18, 0.1, 0.02), 0.03, 12),
                   ("cyl", (0.18, 0.1, 0.02), (0.18, 0.1, 0.09), 0.006, 6), ("cyl", (0.18, 0.1, 0.09), (0.18, 0.1, 0.17), 0.035, 14)]
        return mesh_object(f"FineDiningSettingFactory({self.seed}).spawn_asset({i})", [(plate, diner), (napkin, nap), (steel, cut), (glass, glasses)], bevel=False)


# catalog / _cls build a factory with `cls(seed)` only, so the variants are subclasses with the kind fixed
class MarbleTableLowFactory(BlackMarbleTableFactory):
    def __init__(self, seed):
        super().__init__(seed, "low")


class MarbleTableHighFactory(BlackMarbleTableFactory):
    def __init__(self, seed):
        super().__init__(seed, "high")


class MarbleTableRoundFactory(BlackMarbleTableFactory):
    def __init__(self, seed):
        super().__init__(seed, "round")


class BarStoolWhiteFactory(BarStoolFactory):
    def __init__(self, seed):
        super().__init__(seed, "white")


class BarStoolGoldFactory(BarStoolFactory):
    def __init__(self, seed):
        super().__init__(seed, "gold")


class CreamBanquetteFactory:
    """Cream leather banquette (rooftop VLM gap: 'cream sofa with orange cushions'): proc_assets.BanquetteFactory in cream, plus 2-3 orange cushions leaning on its back."""
    def __new__(cls, seed):
        pa = fl._pa()
        inst = pa.BanquetteFactory(seed)
        inst.c = (0.86, 0.83, 0.72)
        inst._cream_seed = seed
        base_spawn = inst.spawn_asset

        def spawn(i, _b=base_spawn, _inst=inst):
            o = _b(i)
            r = random.Random(_inst._cream_seed * 3 + i)
            orange = fl._flat("ir_rt_cushion_orange", (0.8, 0.32, 0.08), 0.85)
            n = r.randint(2, 3); L = _inst.L
            parts = [("box", -0.1, -L / 2 + 0.5 + k * (L - 1.0) / max(1, n - 1) + r.uniform(-0.05, 0.05), 0.68, 0.1, 0.42, 0.38, r.uniform(-0.15, 0.15)) for k in range(n)]
            cush = mesh_object("rt_cushions", [(orange, parts)], bevel=False)
            return pa._join_cloth(o, [cush])
        inst.spawn_asset = spawn
        return inst


class TimberColumnFactory:
    """Column wrapped in vertical timber slats (rooftop VLM: 'timber slat columns'): 0.6 x 0.6 x 3.2 m, 20 slats per side on a dark core, brass base ring."""
    def __init__(self, seed):
        self.seed = seed

    def spawn_asset(self, i):
        oak = fl._flat("ir_rt_timber_slat", (0.55, 0.36, 0.2), 0.45, wood=True); core = fl._flat("ir_rt_timber_core", (0.08, 0.06, 0.04), 0.7)
        brass = fl._flat("ir_rt_brass_ring", (0.8, 0.62, 0.25), 0.3, 1.0); H = 3.2; n = 12; w = 0.6 / n
        slats = []
        for k in range(n):
            o = -0.3 + (k + 0.5) * w
            slats += [("box", 0.3, o, H / 2, 0.04, w * 0.7, H), ("box", -0.3, o, H / 2, 0.04, w * 0.7, H), ("box", o, 0.3, H / 2, w * 0.7, 0.04, H), ("box", o, -0.3, H / 2, w * 0.7, 0.04, H)]
        return mesh_object(f"TimberColumnFactory({self.seed}).spawn_asset({i})", [(core, [("box", 0, 0, H / 2, 0.58, 0.58, H)]), (oak, slats), (brass, [("box", 0, 0, 0.04, 0.66, 0.66, 0.08), ("box", 0, 0, H - 0.04, 0.66, 0.66, 0.08)])], bevel=False)
