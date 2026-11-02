"""Pharmacy props (S16 review vs the reference sheet S16_ref1/2): a dense wall of small drawers, a long white dispensing counter with a green base band and a glowing LED strip, and small uniform packs.
Front +X, back at x = 0 for wall pieces. Kit accent: STYLE['accent_rgb'] (green) / STYLE['band_rgb'] (light green, default 0.5,0.68,0.25).

  PharmacyDrawerWallFactory  2.4 m wide x 0.35 deep x 2.3 m high: a grid of 12 x 12 white drawer fronts (0.2 x 0.19 m) with a coloured label strip and a small pull on each, a green header band on top
  PharmacyCounterFactory     a dispensing counter 4.0 / 5.0 m x 0.75 x 1.05 m: white body, green base band, white top, an LED strip under the top lip (emissive), two monitors with keyboards on the pharmacist side
  SmallPackFactory           a small retail pack (0.04-0.07 deep, 0.06-0.10 wide, 0.09-0.16 high): a white carton body with the label of a pharmacy product (otc / care_box / med_box) on its front face
"""
from __future__ import annotations

import random

import bpy

from room_planner import proc_assets as pa
from room_planner import proc_boutique_flagship as fl
from room_planner.proc_boutique_flagship import mesh_object

TAGS = ((0.15, 0.55, 0.3), (0.2, 0.4, 0.75), (0.9, 0.55, 0.15), (0.75, 0.2, 0.25), (0.55, 0.35, 0.7), (0.3, 0.7, 0.75))


def _band():
    return tuple(pa.STYLE.get("band_rgb") or (0.5, 0.68, 0.25))


class PharmacyDrawerWallFactory:
    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        r = self.r; W, D, H = 2.4, 0.35, 2.3; nc, nr = 12, 12; cw, ch = W / nc, (H - 0.15) / nr
        white = fl._flat("ir_phdraw_white", (0.93, 0.93, 0.92), 0.4); body = fl._flat("ir_phdraw_body", (0.78, 0.8, 0.78), 0.5); band = fl._flat("ir_phdraw_band", _band(), 0.45)
        dark = fl._flat("ir_phdraw_pull", (0.45, 0.47, 0.48), 0.3, 0.8)
        frame = [("box", 0.17, 0, H / 2, D - 0.02, W, H)]
        fronts, pulls, tags = [], [], {}
        for rw in range(nr):
            for cl in range(nc):
                y = -W / 2 + (cl + 0.5) * cw; z = 0.1 + (rw + 0.5) * ch
                fronts.append(("box", D - 0.015, y, z, 0.02, cw - 0.012, ch - 0.012))
                pulls.append(("box", D + 0.005, y, z - ch * 0.28, 0.012, 0.05, 0.008))
                c = r.choice(TAGS); tags.setdefault(c, []).append(("box", D + 0.0, y, z + ch * 0.22, 0.004, cw * 0.55, 0.018))
        groups = [(body, frame), (white, fronts), (dark, pulls), (band, [("box", D / 2, 0, H - 0.03, D, W, 0.06)])]
        groups += [(fl._flat(f"ir_phdraw_tag_{int(c[0] * 100)}_{int(c[1] * 100)}", c, 0.5), ps) for c, ps in tags.items()]
        return mesh_object(f"PharmacyDrawerWallFactory({i}).spawn_asset({i})", groups, bevel=False)


class PharmacyCounterFactory:
    def __init__(self, seed):
        self.r = random.Random(seed); self.L = self.r.choice((4.0, 5.0))

    def spawn_asset(self, i):
        L = self.L
        white = fl._flat("ir_phc_white", (0.94, 0.94, 0.93), 0.35); band = fl._flat("ir_phc_band", _band(), 0.45); top = fl._flat("ir_phc_top", (0.96, 0.96, 0.95), 0.25)
        led = pa._flat("ir_phc_led", (1.0, 0.97, 0.88), 0.3); b = led.node_tree.nodes["Principled BSDF"]
        b.inputs["Emission Color"].default_value = (1.0, 0.96, 0.85, 1); b.inputs["Emission Strength"].default_value = 7.0
        blk = fl._flat("ir_phc_monitor", (0.04, 0.04, 0.05), 0.4, 0.4); scr = pa._flat("ir_phc_screen", (0.1, 0.18, 0.25), 0.2)
        groups = [(white, [("box", 0.28, 0, 0.5, 0.56, L, 0.9)]), (band, [("box", 0.285, 0, 0.07, 0.575, L + 0.01, 0.14)]), (top, [("box", 0.34, 0, 1.03, 0.68, L + 0.04, 0.05)]),
                  (led, [("box", 0.32, 0, 0.99, 0.6, L - 0.1, 0.012)])]
        mon = []
        for yy in (-L * 0.3, L * 0.2):
            mon += [("box", -0.05, yy, 1.42, 0.03, 0.5, 0.32), ("box", -0.05, yy, 1.1, 0.12, 0.2, 0.03), ("box", 0.0, yy, 1.08, 0.2, 0.4, 0.015)]
        groups += [(blk, mon), (scr, [("box", -0.033, yy, 1.42, 0.004, 0.46, 0.28) for yy in (-L * 0.3, L * 0.2)])]
        return mesh_object(f"PharmacyCounterFactory({i}).spawn_asset({i})", groups, bevel=False)


def _paper_print(path, tint):
    """Printed paperboard: the label image on a matte coated board (rough ~0.62, specular low, no clearcoat/sheen). One material per image + tint, shared."""
    name = f"ir_pack_print_{path.stem}_{int(tint * 100)}"
    m = bpy.data.materials.get(name)
    if m is not None:
        return m
    m = bpy.data.materials.new(name); m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]; b.inputs["Roughness"].default_value = 0.62
    for nm in ("Specular IOR Level", "Specular"):
        if nm in b.inputs:
            b.inputs[nm].default_value = 0.2
    im = bpy.data.images.load(str(path), check_existing=True); im.colorspace_settings.name = "sRGB"
    t = m.node_tree.nodes.new("ShaderNodeTexImage"); t.image = im; t.extension = "EXTEND"
    mix = m.node_tree.nodes.new("ShaderNodeMix"); mix.data_type = "RGBA"; mix.blend_type = "MULTIPLY"; mix.inputs[0].default_value = 1.0
    mix.inputs[7].default_value = (tint, tint, tint, 1)                                            # per-box board tone
    m.node_tree.links.new(t.outputs["Color"], mix.inputs[6]); m.node_tree.links.new(mix.outputs[2], b.inputs["Base Color"])
    return m


class SmallPackFactory:
    """A printed paperboard carton (user 10-21: 'the medicine boxes do not look like paper'): matte coated board, crisp square edges (no bevel), tuck-flap seam lines on the top and the front
    top edge, a glued side seam, the printed label (otc / care_box / med_box designs) on the front, a coloured side band, per-box tone; three shapes: carton, blister-pack flat box, tall bottle carton."""
    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        r = self.r
        kind = r.choices(("box", "blister", "bottle"), (5, 2, 3))[0]
        if kind == "box":
            d, w, h = r.uniform(0.04, 0.07), r.uniform(0.06, 0.10), r.uniform(0.09, 0.16)
        elif kind == "blister":
            d, w, h = r.uniform(0.02, 0.03), r.uniform(0.09, 0.12), r.uniform(0.11, 0.15)
        else:
            d, w, h = r.uniform(0.04, 0.05), r.uniform(0.04, 0.05), r.uniform(0.11, 0.16)
        files = []
        for pat in ("otc_*.png", "care_box_*.png"):
            files += sorted(pa.PRINT_ROOT.parent.joinpath("product_labels_v2").glob(pat))
        files += sorted(pa.PRINT_ROOT.parent.joinpath("product_labels").glob("med_box_*.png"))
        tint = r.choice((0.84, 0.88, 0.92, 0.96))
        tone = (tint, tint * 0.99, tint * 0.96)
        body = fl._flat(f"ir_paperboard_carton_{int(tint * 100)}", tone, 0.65)
        seam = fl._flat("ir_paperboard_carton_seam", (0.55, 0.55, 0.52), 0.7)
        c = r.choice(TAGS); band = fl._flat(f"ir_paperboard_carton_band_{int(c[0] * 100)}_{int(c[1] * 100)}", c, 0.6)
        groups = [(body, [("box", 0, 0, h / 2, d, w, h)])]
        if files:
            groups.append((_paper_print(files[r.randrange(len(files))], tint), [("box", d / 2 + 0.0006, 0, h / 2, 0.001, w, h)]))
        xs = d / 2 + 0.0014
        lines = [("box", d * 0.28, 0, h + 0.0003, 0.0007, w, 0.0006),                           # top tuck-flap seam
                 ("box", xs, 0, h - 0.007, 0.0006, w, 0.0007),                                  # the flap edge on the front
                 ("box", xs, 0, 0.007, 0.0006, w, 0.0007)]                                      # and the bottom flap
        sy = r.choice((1, -1))
        lines.append(("box", -d * 0.15, sy * (w / 2 + 0.0003), h / 2, 0.0008, 0.0006, h))       # the glued side seam
        groups += [(seam, lines), (band, [("box", 0, sy * -(w / 2 + 0.0003), h * 0.3, d * 0.98, 0.0006, h * 0.35)])]
        return mesh_object(f"SmallPackFactory({i}).spawn_asset({i})", groups, bevel=False)
