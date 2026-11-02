"""Props for the warm clinic reception LOBBY (VLM reference S17 / D3: oak louver desk, oak-panelled feature wall, beige sofa and light-oak armchairs, round oak
coffee table, jute rug, framed botanical art). Flag ROOM_CLINIC_LOBBY=1, venue stays 'clinic-reception'.

Factory-shaped like proc_assets (Cls(seed).spawn_asset(i), front +X, origin at the bottom centre; wall pieces have their back at x = 0); one merged mesh per object:

  OakLouverDeskFactory     reception desk 2.8-3.6 x 0.75 x 1.05 m: ~30 vertical oak slats on the visitor side, white stone top (overhang 6 cm), a warm LED strip
                           under the top edge (emissive geometry), a lower staff worktop behind
  BeigeSofaFactory         2.0 m three-seat sofa: base, 3 seat + 3 back cushions in beige weave (soft bevel), light-oak legs and arm slabs
  OakArmchairFactory       0.8 x 0.85 m armchair: light-oak frame with open arms, beige seat and back cushions
  RoundOakCoffeeTableFactory  0.9-1.0 m round oak top on three splayed legs, 0.42 m high
  JuteRugFactory           2.4 x 1.7 m flat rug (1.2 cm) with a woven jute pattern + bump (procedural)
  WoodPanelWallFactory     3.6 m wide x 2.5 m high slatted oak panel wall (back at x = 0) with a warm LED backsplash strip at 1.1 m
  FramedBotanicalArtFactory  a pale frame around a print from data/venue_refs/prop_textures (wall_art_*), 0.9 x 1.2 m
  PlanterTallFactory       not here: tall plants use the catalog's floor_plant (Infinigen) so they stay procedural leaves
"""
from __future__ import annotations

import glob
import math
import random
from pathlib import Path

import bpy

from room_planner import proc_boutique_flagship as fl
from room_planner.proc_boutique_flagship import mesh_object

PRINTS = Path("/jarvis/project/robomituba/data/venue_refs/prop_textures")
OAK = (0.72, 0.52, 0.32)          # light oak
OAK_DARK = (0.5, 0.33, 0.18)
BEIGE = (0.62, 0.56, 0.47)


def _emit(name, rgb, strength):
    m = bpy.data.materials.get(name)
    if m is not None:
        return m
    m = bpy.data.materials.new(name); m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*rgb, 1); b.inputs["Roughness"].default_value = 0.5
    b.inputs["Emission Color"].default_value = (*rgb, 1); b.inputs["Emission Strength"].default_value = strength
    return m


def _oak(name="ir_cl_oak", rgb=OAK):
    return fl._flat(name, rgb, 0.5, 0.0, wood=True)


def _soft(o, width=0.035, seg=2):
    """A soft edge (bevel modifier, left live: upholstery must not look like boxes)."""
    md = o.modifiers.new("ir_soft", "BEVEL"); md.width = width; md.segments = seg; md.limit_method = "ANGLE"
    return o


class OakLouverDeskFactory:
    def __init__(self, seed):
        r = random.Random(seed); self.L = r.choice((2.8, 3.2, 3.6)); self.seed = seed

    def spawn_asset(self, i):
        L, D, H = self.L, 0.75, 1.05
        oak = _oak(); core = fl._flat("ir_cl_desk_core", (0.16, 0.12, 0.08), 0.7)
        stone = fl._flat("ir_cl_stone_top", (0.86, 0.83, 0.77), 0.3)
        led = _emit("ir_cl_led_warm", (1.0, 0.72, 0.4), 7.0)
        n = int(L / 0.1); pitch = L / n
        slats = [("box", D / 2 + 0.005, -L / 2 + (k + 0.5) * pitch, (H - 0.05) / 2, 0.035, pitch * 0.62, H - 0.07) for k in range(n)]
        back = [("box", -D / 2 + 0.05, 0, (H - 0.05) / 2 + 0.0, 0.06, L, H - 0.05), ("box", 0.0, 0, 0.04, D - 0.1, L, 0.08)]
        top = [("box", 0.04, 0, H - 0.025, D + 0.12, L + 0.06, 0.05), ("box", -0.22, 0, H - 0.3, 0.3, L - 0.1, 0.03)]   # top with overhang + a lower staff worktop behind
        ledg = [("box", D / 2 + 0.05, 0, H - 0.07, 0.01, L - 0.1, 0.025)]
        return mesh_object(f"OakLouverDeskFactory({self.seed}).spawn_asset({i})", [(oak, slats), (core, back), (stone, top), (led, ledg)], bevel=False)


class BeigeSofaFactory:
    def __init__(self, seed):
        self.seed = seed

    def spawn_asset(self, i):
        r = random.Random(self.seed * 5 + i); L, D = 2.0, 0.9
        fab = fl._flat("ir_cl_beige_weave", BEIGE, 0.92); oak = _oak("ir_cl_oak_light", (0.78, 0.6, 0.38))
        base = [("box", 0, 0, 0.22, D - 0.05, L - 0.1, 0.24)]
        seat = [("box", 0.05, -L / 2 + 0.38 + k * (L - 0.76) / 2, 0.42, D - 0.2, (L - 0.76) / 3 * 1.4, 0.16) for k in range(3)]
        backs = [("box", -D / 2 + 0.16, -L / 2 + 0.38 + k * (L - 0.76) / 2, 0.66, 0.2, (L - 0.76) / 3 * 1.4, 0.42, 0.0) for k in range(3)]
        pill = [("box", -D / 2 + 0.3, r.choice((-1, 1)) * (L / 2 - 0.45), 0.62, 0.12, 0.42, 0.4, r.uniform(-0.2, 0.2))]
        legs = [("box", sx * (D / 2 - 0.08), sy * (L / 2 - 0.1), 0.06, 0.05, 0.05, 0.12) for sx in (1, -1) for sy in (1, -1)]
        arms = [("box", 0, sy * (L / 2 - 0.05), 0.5, D - 0.05, 0.1, 0.06) for sy in (1, -1)] + [("box", 0, sy * (L / 2 - 0.05), 0.3, 0.06, 0.08, 0.34) for sy in (1, -1)]
        o = mesh_object(f"BeigeSofaFactory({self.seed}).spawn_asset({i})", [(fab, base + seat + backs + pill), (oak, legs + arms)], bevel=False)
        return _soft(o)


class OakArmchairFactory:
    def __init__(self, seed):
        self.seed = seed

    def spawn_asset(self, i):
        fab = fl._flat("ir_cl_beige_weave", BEIGE, 0.92); oak = _oak("ir_cl_oak_light", (0.78, 0.6, 0.38))
        W, D = 0.8, 0.85
        cush = [("box", 0.05, 0, 0.4, D - 0.25, W - 0.28, 0.14), ("box", -D / 2 + 0.2, 0, 0.62, 0.14, W - 0.3, 0.42)]
        frame = [("box", sx * (D / 2 - 0.06), sy * (W / 2 - 0.05), 0.15, 0.05, 0.05, 0.3) for sx in (1, -1) for sy in (1, -1)]
        frame += [("box", 0.0, sy * (W / 2 - 0.05), 0.5, D - 0.05, 0.06, 0.05) for sy in (1, -1)] + [("box", -D / 2 + 0.05, sy * (W / 2 - 0.05), 0.45, 0.05, 0.05, 0.35) for sy in (1, -1)]
        frame += [("box", 0.0, 0, 0.3, D - 0.1, W - 0.1, 0.05)]
        o = mesh_object(f"OakArmchairFactory({self.seed}).spawn_asset({i})", [(fab, cush), (oak, frame)], bevel=False)
        return _soft(o, 0.03)


class RoundOakCoffeeTableFactory:
    def __init__(self, seed):
        r = random.Random(seed); self.R = r.choice((0.45, 0.5)); self.seed = seed

    def spawn_asset(self, i):
        oak = _oak("ir_cl_oak_light", (0.78, 0.6, 0.38)); R = self.R
        legs = [("cyl", (0.3 * R * math.cos(a), 0.3 * R * math.sin(a), 0.38), (0.78 * R * math.cos(a), 0.78 * R * math.sin(a), 0.0), 0.022, 8) for a in (0.5, 2.6, 4.7)]
        top = [("cyl", (0, 0, 0.38), (0, 0, 0.42), R, 28)]
        r = random.Random(self.seed + 7)                                       # S17 r31 CNT-01: a bare waiting table: two or three magazines fanned in a stack and a ceramic bowl
        covers = [fl._flat(f"ir_cl_mag_{k}", c, 0.6) for k, c in enumerate(((0.72, 0.62, 0.5), (0.45, 0.55, 0.5), (0.85, 0.8, 0.72), (0.6, 0.45, 0.4)))]
        cer = fl._flat("ir_cl_ceramic_cream", (0.92, 0.89, 0.82), 0.35)
        mags = [(covers[(k + self.seed) % 4], [("box", -0.08 * R + 0.012 * k, 0.04 * R * r.uniform(-1, 1), 0.42 + 0.005 + 0.007 * k, 0.21, 0.28, 0.006, r.uniform(-0.5, 0.5) + 0.3 * k)]) for k in range(r.choice((2, 3)))]
        bowl = [("cyl", (0.45 * R, -0.2 * R, 0.42), (0.45 * R, -0.2 * R, 0.465), 0.075, 20), ("cyl", (0.45 * R, -0.2 * R, 0.465), (0.45 * R, -0.2 * R, 0.47), 0.06, 20)]
        return mesh_object(f"RoundOakCoffeeTableFactory({self.seed}).spawn_asset({i})", [(oak, top + legs), (cer, bowl)] + mags, bevel=False)


class JuteRugFactory:
    def __init__(self, seed):
        self.seed = seed

    def spawn_asset(self, i):
        m = bpy.data.materials.get("ir_cl_jute")
        if m is None:
            m = bpy.data.materials.new("ir_cl_jute"); m.use_nodes = True
            nt = m.node_tree; N, L = nt.nodes, nt.links; b = N["Principled BSDF"]
            tc = N.new("ShaderNodeTexCoord"); mp = N.new("ShaderNodeMapping"); mp.inputs["Scale"].default_value = (22.0, 22.0, 22.0); L.new(tc.outputs["Object"], mp.inputs["Vector"])
            br = N.new("ShaderNodeTexBrick"); br.inputs["Scale"].default_value = 1.0; br.inputs["Mortar Size"].default_value = 0.12; br.inputs["Color1"].default_value = (0.58, 0.46, 0.32, 1)
            br.inputs["Color2"].default_value = (0.5, 0.39, 0.27, 1); br.inputs["Mortar"].default_value = (0.36, 0.28, 0.2, 1); L.new(mp.outputs["Vector"], br.inputs["Vector"])
            nz = N.new("ShaderNodeTexNoise"); nz.inputs["Scale"].default_value = 90.0; nz.inputs["Detail"].default_value = 5; L.new(tc.outputs["Object"], nz.inputs["Vector"])
            mix = N.new("ShaderNodeMix"); mix.data_type = "RGBA"; mix.blend_type = "MULTIPLY"; mix.inputs["Factor"].default_value = 0.35
            L.new(br.outputs["Color"], mix.inputs[6]); L.new(nz.outputs["Color"], mix.inputs[7]); L.new(mix.outputs[2], b.inputs["Base Color"])
            bump = N.new("ShaderNodeBump"); bump.inputs["Strength"].default_value = 0.6; bump.inputs["Distance"].default_value = 0.004; L.new(br.outputs["Fac"], bump.inputs["Height"]); L.new(bump.outputs["Normal"], b.inputs["Normal"])
            b.inputs["Roughness"].default_value = 0.95
        return mesh_object(f"JuteRugFactory({self.seed}).spawn_asset({i})", [(m, [("box", 0, 0, 0.006, 1.7, 2.4, 0.012)])], bevel=False)


class WoodPanelWallFactory:
    def __init__(self, seed):
        r = random.Random(seed); self.W = r.choice((3.2, 3.6)); self.seed = seed

    def spawn_asset(self, i):
        W, H = self.W, 2.5
        oak = _oak("ir_cl_oak_panel", (0.7, 0.5, 0.3)); core = fl._flat("ir_cl_panel_core", (0.14, 0.1, 0.06), 0.7); led = _emit("ir_cl_led_warm", (1.0, 0.72, 0.4), 7.0)
        n = int(W / 0.075); pitch = W / n
        slats = [("box", 0.04, -W / 2 + (k + 0.5) * pitch, H / 2, 0.04, pitch * 0.72, H) for k in range(n)]
        back = [("box", 0.01, 0, H / 2, 0.02, W, H), ("box", 0.14, 0, 1.0, 0.2, W - 0.3, 0.03)]            # back panel + a shelf ledge at 1.0 m
        strip = [("box", 0.06, 0, 1.12, 0.012, W - 0.4, 0.025)]
        return mesh_object(f"WoodPanelWallFactory({self.seed}).spawn_asset({i})", [(core, back), (oak, slats), (led, strip)], bevel=False)


class FramedBotanicalArtFactory:
    def __init__(self, seed):
        calm = ("01", "02", "04", "06")                                       # abstract, leaves, lake, line art: not the coffee cup / city / map / slogan prints (S17 r31 DOM-01: a coffee advert in a clinic)
        files = sorted(f for f in glob.glob(str(PRINTS / "wall_art_*.png")) if Path(f).stem[-2:] in calm) or sorted(glob.glob(str(PRINTS / "poster_health_*.png")))
        self.img = random.Random(seed).choice(files) if files else None; self.seed = seed

    def spawn_asset(self, i):
        W, H = 0.9, 1.2
        frame = fl._flat("ir_cl_frame_pale", (0.8, 0.72, 0.6), 0.45); mat = fl._flat("ir_cl_mat_white", (0.93, 0.91, 0.86), 0.7)
        groups = [(frame, [("box", 0.02, 0, H / 2, 0.04, W, H)]), (mat, [("box", 0.043, 0, H / 2, 0.006, W - 0.1, H - 0.1)])]
        if self.img:
            nm = "ir_cl_art_" + Path(self.img).stem
            pm = bpy.data.materials.get(nm)
            if pm is None:
                pm = bpy.data.materials.new(nm); pm.use_nodes = True
                nt = pm.node_tree; b = nt.nodes["Principled BSDF"]
                t = nt.nodes.new("ShaderNodeTexImage"); t.image = bpy.data.images.load(self.img, check_existing=True)
                nt.links.new(t.outputs["Color"], b.inputs["Base Color"]); b.inputs["Roughness"].default_value = 0.6
            groups.append((pm, [("box", 0.048, 0, H / 2, 0.004, W - 0.22, H - 0.22)]))
        return mesh_object(f"FramedBotanicalArtFactory({self.seed}).spawn_asset({i})", groups, bevel=False)
