"""Props for the underground wine pub (reference set wine_pub_underground_01; docs/wine_pub_underground_design_proposal.md). Flag ROOM_WINEPUB=1 on 'cafe'.

Factory-shaped like proc_assets (Cls(seed).spawn_asset(i), front +X, origin at the bottom centre; wall pieces have their back at x = 0).
Everything is boxes / cylinders / icospheres merged into ONE mesh per object (proc_boutique_flagship.mesh_object); bottles and fairy lights are
emissive points in the same mesh, not real lights:

  WhiteMarbleRoundTableFactory  round white marble top (0.6-0.7 m dia, 0.74 m) on a black tulip pedestal; a tea-light glass
  VelvetShellChairFactory       burgundy velvet shell chair on a 4-leg chrome swivel base (0.55 x 0.55 x 0.8, seat 0.46)
  BottleRowFactory              a row of 18-30 bottles standing along a line (floor-edge display) with a string of warm fairy-light bulbs; length 2.4 m
  BottleShelfFactory            black steel angle shelf 1.5 x 0.4 x 1.9 m, 4 levels, 3 bottle rows per level (~120 bottles), back at x = 0
  MirrorBallFactory             a 0.4 m mirror ball on a rod (hangs from z = 0 down) + 3 small silver spheres
  SilverSphereClusterFactory    8-14 silver spheres 8-16 cm dia hung at different heights from the ceiling (origin at the ceiling, hangs down)
  WrinkledMirrorWallFactory     a wall of vertical mirrored half-pipes, 2.4 m wide x 2.3 m high (back at x = 0)
  BarCounterBlackFactory        black bar counter 3.6 x 0.65 x 1.05 m with a dark top and a foot rail (back at x = 0)
"""
from __future__ import annotations

import math
import random

import bpy

from room_planner import proc_boutique_flagship as fl
from room_planner.proc_boutique_flagship import mesh_object


def _emit(name, rgb, strength):
    m = bpy.data.materials.get(name)
    if m is not None:
        return m
    m = bpy.data.materials.new(name); m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*rgb, 1); b.inputs["Roughness"].default_value = 0.4
    b.inputs["Emission Color"].default_value = (*rgb, 1); b.inputs["Emission Strength"].default_value = strength
    return m


def _glass_dark(name, rgb, rough=0.08):
    """A tinted glossy bottle without transmission (hundreds of them: transmission would multiply render time)."""
    return fl._flat(name, rgb, rough, 0.0)


BOTTLE_COLORS = {"green": (0.03, 0.1, 0.05), "amber": (0.25, 0.1, 0.02), "clear": (0.55, 0.6, 0.58), "dark": (0.02, 0.015, 0.02), "blue": (0.04, 0.1, 0.25)}
LABEL = (0.85, 0.82, 0.72)


def _bottle(rng, x, y, z, groups, label_mat_key="label", h=None):
    """One bottle standing at (x, y, z): body cylinder + shoulder + neck + cap + label band."""
    col = rng.choice(("green", "green", "amber", "clear", "clear", "dark", "blue")); h = h or rng.uniform(0.26, 0.34); r = rng.uniform(0.032, 0.04)
    gl = groups.setdefault(col, [])
    gl.append(("cyl", (x, y, z), (x, y, z + h * 0.62), r, 8))
    gl.append(("cyl", (x, y, z + h * 0.62), (x, y, z + h), r * 0.38, 6))
    groups.setdefault(label_mat_key, []).append(("cyl", (x, y, z + h * 0.18), (x, y, z + h * 0.44), r * 1.02, 8))
    groups.setdefault("cap", []).append(("cyl", (x, y, z + h), (x, y, z + h + 0.025), r * 0.4, 6))


def _bottle_mats():
    m = {k: _glass_dark(f"ir_wp_glass_{k}", c) for k, c in BOTTLE_COLORS.items()}
    m["label"] = fl._flat("ir_wp_label", LABEL, 0.7); m["cap"] = fl._flat("ir_wp_cap", (0.7, 0.55, 0.25), 0.3, 0.9)
    return m



def _scuff(mat, r0, r1):
    """Worn finish (S23 r6 SRF-02: 'the bar top is spotless'): roughness driven by fine noise between r0 and r1, plus a faint scratch bump."""
    import bpy
    if mat.get("scuffed"):
        return
    nt = mat.node_tree; N, Lk = nt.nodes, nt.links; b = N["Principled BSDF"]
    tc = N.new("ShaderNodeTexCoord"); mp = N.new("ShaderNodeMapping"); mp.inputs["Scale"].default_value = (4.0, 4.0, 4.0)
    n1 = N.new("ShaderNodeTexNoise"); n1.inputs["Scale"].default_value = 9.0; n1.inputs["Detail"].default_value = 8.0
    n2 = N.new("ShaderNodeTexNoise"); n2.inputs["Scale"].default_value = 90.0; n2.inputs["Detail"].default_value = 2.0
    rr = N.new("ShaderNodeMapRange"); rr.inputs["To Min"].default_value = r0; rr.inputs["To Max"].default_value = r1
    bp = N.new("ShaderNodeBump"); bp.inputs["Strength"].default_value = 0.04; bp.inputs["Distance"].default_value = 0.002
    Lk.new(tc.outputs["Object"], mp.inputs["Vector"]); Lk.new(mp.outputs["Vector"], n1.inputs["Vector"]); Lk.new(mp.outputs["Vector"], n2.inputs["Vector"])
    Lk.new(n1.outputs["Fac"], rr.inputs["Value"]); Lk.new(rr.outputs["Result"], b.inputs["Roughness"])
    Lk.new(n2.outputs["Fac"], bp.inputs["Height"]); Lk.new(bp.outputs["Normal"], b.inputs["Normal"])
    mat["scuffed"] = True

class WhiteMarbleRoundTableFactory:
    def __init__(self, seed):
        r = random.Random(seed); self.D = r.choice((0.6, 0.65, 0.7)); self.seed = seed

    def spawn_asset(self, i):
        pa = fl._pa()
        top = bpy.data.materials.get("ir_wp_marble_white") or self._marble()
        black = fl._flat("ir_wp_pedestal", (0.03, 0.03, 0.035), 0.4, 0.6)
        glass = _glass_dark("ir_wp_tealight_glass", (0.7, 0.75, 0.72), 0.05)
        flame = _emit("ir_wp_flame", (1.0, 0.8, 0.5), 25.0)
        H, R = 0.74, self.D / 2
        parts = [("cyl", (0, 0, 0.0), (0, 0, H - 0.03), 0.03, 10), ("cyl", (0, 0, 0.0), (0, 0, 0.02), 0.22, 18), ("cyl", (0, 0, H - 0.05), (0, 0, H - 0.03), 0.09, 12)]
        tops = [("cyl", (0, 0, H - 0.03), (0, 0, H), R, 28)]
        glasses = [("cyl", (0.1, 0.08, H), (0.1, 0.08, H + 0.045), 0.028, 12)]
        flames = [("cyl", (0.1, 0.08, H + 0.01), (0.1, 0.08, H + 0.04), 0.017, 8)]
        return mesh_object(f"WhiteMarbleRoundTableFactory({self.seed}).spawn_asset({i})", [(black, parts), (top, tops), (glass, glasses), (flame, flames)], bevel=False)

    @staticmethod
    def _marble():
        m = bpy.data.materials.new("ir_wp_marble_white"); m.use_nodes = True
        nt = m.node_tree; N, L = nt.nodes, nt.links; b = N["Principled BSDF"]
        tc = N.new("ShaderNodeTexCoord"); mp = N.new("ShaderNodeMapping"); mp.inputs["Scale"].default_value = (2.0, 2.0, 2.0); L.new(tc.outputs["Object"], mp.inputs["Vector"])
        nz = N.new("ShaderNodeTexNoise"); nz.inputs["Scale"].default_value = 2.2; nz.inputs["Detail"].default_value = 9; nz.inputs["Distortion"].default_value = 1.1
        L.new(mp.outputs["Vector"], nz.inputs["Vector"])
        ab = N.new("ShaderNodeMath"); ab.operation = "SUBTRACT"; ab.inputs[1].default_value = 0.5; L.new(nz.outputs["Fac"], ab.inputs[0])
        ab2 = N.new("ShaderNodeMath"); ab2.operation = "ABSOLUTE"; L.new(ab.outputs["Value"], ab2.inputs[0])
        rp = N.new("ShaderNodeValToRGB"); rp.color_ramp.elements[0].position = 0.0; rp.color_ramp.elements[1].position = 0.05
        rp.color_ramp.elements[0].color = (0.62, 0.5, 0.38, 1); rp.color_ramp.elements[1].color = (0.82, 0.78, 0.7, 1); L.new(ab2.outputs["Value"], rp.inputs["Fac"])
        L.new(rp.outputs["Color"], b.inputs["Base Color"]); b.inputs["Roughness"].default_value = 0.18; b.inputs["Coat Weight"].default_value = 0.3
        return m


class VelvetShellChairFactory:
    """Burgundy velvet shell chair (front +X): a curved shell approximated by a seat slab, a back slab leaning 12 deg and two side wings; chrome 4-leg base."""
    def __init__(self, seed):
        r = random.Random(seed); self.c = r.choice(((0.28, 0.03, 0.06), (0.22, 0.02, 0.05), (0.32, 0.05, 0.07))); self.seed = seed

    def spawn_asset(self, i):
        v = fl._flat(f"ir_wp_velvet_{int(self.c[0] * 100)}", self.c, 0.9)
        chrome = fl._flat("ir_wp_chrome", (0.85, 0.85, 0.87), 0.15, 1.0)
        shell = [("box", 0.0, 0, 0.5, 0.5, 0.52, 0.1), ("box", -0.22, 0, 0.72, 0.07, 0.52, 0.42, 0.0)]
        shell += [("box", -0.08, sy * 0.27, 0.68, 0.34, 0.06, 0.3) for sy in (1, -1)]
        base = [("cyl", (0, 0, 0.0), (0, 0, 0.44), 0.025, 8)] + [("cyl", (0, 0, 0.02), (0.26 * math.cos(a), 0.26 * math.sin(a), 0.0), 0.012, 6) for a in (0.4, 1.97, 3.54, 5.11)]
        return mesh_object(f"VelvetShellChairFactory({self.seed}).spawn_asset({i})", [(v, shell), (chrome, base)])


class BottleRowFactory:
    """Bottles standing in a row along local y (2.4 m), with a string of warm fairy-light bulbs along the front (origin at the row's centre on the floor)."""
    def __init__(self, seed):
        self.seed = seed

    def spawn_asset(self, i):
        r = random.Random(self.seed * 31 + i); mats = _bottle_mats(); groups = {}
        n = r.randint(22, 30)
        for k in range(n):
            _bottle(r, r.uniform(-0.03, 0.03), -1.2 + 0.05 + k * 2.3 / (n - 1), 0.0, groups)
        fairy = [("sph", (0.07, -1.2 + 0.04 * k, 0.03 + 0.015 * math.sin(k * 0.9)), 0.011, 1) for k in range(60)]
        wire = [("cyl", (0.07, -1.2, 0.02), (0.07, 1.2, 0.02), 0.002, 4)]
        glow = _emit("ir_wp_fairy", (1.0, 0.86, 0.55), 18.0); wire_m = fl._flat("ir_wp_wire", (0.8, 0.7, 0.4), 0.4, 1.0)
        return mesh_object(f"BottleRowFactory({self.seed}).spawn_asset({i})", [(mats[c], parts) for c, parts in groups.items()] + [(glow, fairy), (wire_m, wire)], bevel=False)


class BottleShelfFactory:
    """Black steel angle shelf (back at x = 0, front +X), 1.5 m wide x 0.4 deep x 1.9 high, 4 levels, 3 rows of bottles per level."""
    def __init__(self, seed):
        self.seed = seed

    def spawn_asset(self, i):
        r = random.Random(self.seed * 37 + i); mats = _bottle_mats(); steel = fl._flat("ir_wp_angle_steel", (0.05, 0.05, 0.055), 0.45, 0.8)
        W, D, H = 1.5, 0.4, 1.9
        frame = [("box", 0.02, sy * (W / 2 - 0.02), H / 2, 0.04, 0.04, H) for sy in (1, -1)] + [("box", D - 0.02, sy * (W / 2 - 0.02), H / 2, 0.04, 0.04, H) for sy in (1, -1)]
        levels = [0.35 + k * 0.45 for k in range(4)]
        shelves = [("box", D / 2, 0, z, D, W, 0.03) for z in levels]
        groups = {}
        for z in levels:
            for row in range(3):
                x = 0.1 + row * 0.1
                for k in range(int((W - 0.12) / 0.075)):
                    if r.random() < 0.12:
                        continue
                    _bottle(r, x, -W / 2 + 0.07 + k * 0.075, z + 0.015, groups)
        return mesh_object(f"BottleShelfFactory({self.seed}).spawn_asset({i})", [(steel, frame + shelves)] + [(mats[c], parts) for c, parts in groups.items()], bevel=False)


class MirrorBallFactory:
    """A mirror ball hung from z = 0 (origin at the ceiling) with three small silver spheres beside it."""
    def __init__(self, seed):
        self.seed = seed

    def spawn_asset(self, i):
        mirror = fl._flat("ir_wp_mirrorball", (0.9, 0.9, 0.92), 0.04, 1.0); rod = fl._flat("ir_wp_rod", (0.1, 0.1, 0.1), 0.5, 0.5)
        parts = [("sph", (0, 0, -0.7), 0.34, 3), ("sph", (0.65, 0.3, -0.5), 0.1, 2), ("sph", (-0.6, -0.35, -0.6), 0.09, 2), ("sph", (0.15, -0.7, -0.42), 0.11, 2)]
        rods = [("cyl", (0, 0, 0), (0, 0, -0.36), 0.004, 4), ("cyl", (0.45, 0.2, 0), (0.45, 0.2, -0.38), 0.003, 4), ("cyl", (-0.4, -0.25, 0), (-0.4, -0.25, -0.49), 0.003, 4), ("cyl", (0.1, -0.5, 0), (0.1, -0.5, -0.3), 0.003, 4)]
        return mesh_object(f"MirrorBallFactory({self.seed}).spawn_asset({i})", [(mirror, parts), (rod, rods)], bevel=False)


class SilverSphereClusterFactory:
    """8-14 silver spheres at different drops from the ceiling (origin at the ceiling)."""
    def __init__(self, seed):
        self.seed = seed

    def spawn_asset(self, i):
        r = random.Random(self.seed * 41 + i); mirror = fl._flat("ir_wp_silver", (0.85, 0.85, 0.88), 0.06, 1.0); rod = fl._flat("ir_wp_rod", (0.1, 0.1, 0.1), 0.5, 0.5)
        sph, rods = [], []
        for _ in range(r.randint(8, 14)):
            x, y, d, rad = r.uniform(-0.9, 0.9), r.uniform(-0.9, 0.9), r.uniform(0.25, 0.75), r.uniform(0.04, 0.09)
            sph.append(("sph", (x, y, -d), rad, 2)); rods.append(("cyl", (x, y, 0), (x, y, -d + rad), 0.0025, 4))
        return mesh_object(f"SilverSphereClusterFactory({self.seed}).spawn_asset({i})", [(mirror, sph), (rod, rods)], bevel=False)


class WrinkledMirrorWallFactory:
    """A wall of vertical mirrored half-pipes 2.4 m wide x 2.3 m high (back at x = 0): 40 pipes, alternating radius."""
    def __init__(self, seed):
        self.seed = seed

    def spawn_asset(self, i):
        r = random.Random(self.seed * 43 + i); mirror = fl._flat("ir_wp_mirrorpipe", (0.8, 0.78, 0.74), 0.07, 1.0); back = fl._flat("ir_wp_mirrorback", (0.04, 0.04, 0.045), 0.6)
        n = 40; pitch = 2.4 / n; pipes = []
        for k in range(n):
            y = -1.2 + (k + 0.5) * pitch; rad = pitch * 0.5 * r.uniform(0.9, 1.1)
            pipes.append(("cyl", (rad * 0.4, y, 0.05), (rad * 0.4, y, 2.3), rad, 8))
        return mesh_object(f"WrinkledMirrorWallFactory({self.seed}).spawn_asset({i})", [(back, [("box", 0.01, 0, 1.15, 0.02, 2.4, 2.3)]), (mirror, pipes)], bevel=False)


class BarCounterBlackFactory:
    """Black bar counter (back at x = 0 toward the bar, front +X toward the guests): 3.6 x 0.65 x 1.05 m with a dark top, a foot rail and a under-lip."""
    def __init__(self, seed):
        self.seed = seed

    def spawn_asset(self, i):
        body = fl._flat("ir_wp_bar_body", (0.03, 0.03, 0.035), 0.45, 0.2); top = fl._flat("ir_wp_bar_top", (0.015, 0.015, 0.02), 0.12, 0.0); _scuff(top, 0.12, 0.5); rail = fl._flat("ir_wp_chrome", (0.85, 0.85, 0.87), 0.15, 1.0)
        L = 3.6
        return mesh_object(f"BarCounterBlackFactory({self.seed}).spawn_asset({i})", [
            (body, [("box", 0.28, 0, 0.5, 0.56, L, 1.0)]), (top, [("box", 0.34, 0, 1.02, 0.68, L + 0.04, 0.05)]),
            (rail, [("cyl", (0.62, -L / 2 + 0.05, 0.15), (0.62, L / 2 - 0.05, 0.15), 0.02, 10)])], bevel=False)


class MirrorPillarFactory:
    """Polished stainless / mirror pillar (wine pub VLM: 'columns read as beige walls'): a 0.76 m dia 24-sided cylinder, 2.5 m high, fully metallic mirror
    (metallic 1, roughness 0.04) with a dark base plinth and a thin glowing amber ring at 0.4 m. Origin at the bottom centre."""
    def __init__(self, seed):
        self.seed = seed

    def spawn_asset(self, i):
        mirror = fl._flat("ir_wp_pillar_mirror", (0.92, 0.9, 0.86), 0.04, 1.0); base = fl._flat("ir_wp_pillar_base", (0.03, 0.03, 0.035), 0.4, 0.8)
        glow = _emit("ir_wp_pillar_glow", (1.0, 0.7, 0.35), 8.0)
        return mesh_object(f"MirrorPillarFactory({self.seed}).spawn_asset({i})", [
            (mirror, [("cyl", (0, 0, 0.08), (0, 0, 2.5), 0.38, 24)]), (base, [("cyl", (0, 0, 0.0), (0, 0, 0.08), 0.42, 24)]), (glow, [("cyl", (0, 0, 0.4), (0, 0, 0.42), 0.385, 24)])], bevel=False)
