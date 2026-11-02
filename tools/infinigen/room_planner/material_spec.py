"""Material specs for the procedural assets: an explicit kind, the physical Principled inputs, and a cache key over the whole spec.

Why (2026-10-17 review of proc_assets._flat, 306 call sites): the scan/detail kind was guessed from substrings of the material name
(153 sites matched none and fell back to shader noise, invisible at 512 px per the G r36 A/B); the only physical inputs were roughness
and metallic (no coat, sheen, subsurface, IOR); and the cache key was the name alone, with 42 names built from one colour channel
(`int(rgb[2] * 100)`), so two colours could share a material.

Default OFF, so running pipelines are unaffected:
  IR_MATSPEC=1        proc_assets._flat builds through `build` below: explicit `kind=` wins, then the legacy name rules, then INFER;
                      a name that is already taken by a different spec gets a `.<hash>` suffix (the first one keeps its plain name,
                      so the startswith("ir_print_") / ("ir_screen_") lookups elsewhere keep working).
  IR_MATSPEC_SCAN=1   stronger scan read per kind (SCAN_PUSH: contrast / tile), A/B values for the 'texture flat' marks;
                      =2 adds a stronger normal map, smaller tiles on wood / laminate and the scan's colour on fabric (SCAN_PUSH2)
  IR_MATSPEC_PHYS=1   additionally applies PHYS (coat / sheen) per kind. These are starting values to A/B, not measurements.
GT: roughness / metallic keep flowing through the Principled sockets. Coat is a separate GT channel (mask it by coat weight > 0);
sheen has no GT channel, so PHYS sheen is the one value to confirm against ir_fixture_contract before it is left on.

`build(pa, ...)` takes the proc_assets module as `pa` to reuse its _scan / _detail / _grain without importing it (it imports us).
"""
from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass

import bpy

ENABLED = os.environ.get("IR_MATSPEC") == "1"
PHYS_ON = os.environ.get("IR_MATSPEC_PHYS") == "1"

#: kinds the scan library can serve (proc_assets.SCANS): wood metal fabric laminate paint card plastic. "upholstery" is fabric's alias.
ALIASES = {"upholstery": "fabric", "steel": "metal", "board": "card"}

#: names the legacy rules miss (the 122 distinct names of 2026-10-17) -> a scan kind. Conservative: only names whose material is
#: unambiguous from the factory docstrings. Everything else stays on the legacy path, and a call site can still pass kind=.
INFER = (
    ("paint", r"^ir_(appliance_white|laminate_white|gondola_white|cooler$|freezer_inner|autoclave_display|stall|fitting_wall|urinal_divider|"
              r"divider|babychange|dental|hook_board|pegboard|menu_frame|pedestal)"),
    ("fabric", r"^ir_(bean_bag|garment|jacket|folded|curtain|mop_grey|shade|bp_cuff)"),
    ("plastic", r"^ir_(cup_lid|sharps_lid|pump_white|sanitizer|glove_white|exam_pad|gym_mat|foam_roller|gymball|bike|mat$|dumbbell|truck)"),
    ("card", r"^ir_(sack|pack$|tin_label|ship_label)"),
    ("wood", r"^ir_(hanger_wood|cutting_board|rail_oak|wallbars_wood|wicker)"),
)

#: per-kind physical inputs, applied only with IR_MATSPEC_PHYS=1 (A/B starting points)
PHYS = {
    "laminate": {"coat": 0.15, "coat_rough": 0.25},      # semi-gloss HPL top
    "paint": {"coat": 0.10, "coat_rough": 0.30},         # satin lacquer on cabinet / locker fronts
    "fabric": {"sheen": 0.40, "sheen_rough": 0.50},      # woven upholstery
}


@dataclass(frozen=True)
class MaterialSpec:
    name: str
    rgb: tuple
    rough: float
    metallic: float = 0.0
    transmission: float = 0.0
    wood: bool = False
    kind: str | None = None
    coat: float = 0.0
    coat_rough: float = 0.1
    sheen: float = 0.0
    sheen_rough: float = 0.5
    subsurface: float = 0.0
    ior: float | None = None
    contrast: float | None = None     # share of the scan's luminance variation kept (proc_assets.SCAN_CONTRAST; default 0.6)
    tile: float | None = None         # metres per scan tile (proc_assets.SCAN_TILE; wood 1.0)
    normal: float | None = None       # normal-map strength on the scan (default 1.0)
    colour: float | None = None       # share of the scan's own colour variation mixed into the grey luminance variation (0 = luminance only)

    def key(self) -> str:
        """Hash of every field, colours to 3 decimals: two specs share a material only if they are the same spec."""
        f = [self.name, *(round(c, 3) for c in self.rgb), round(self.rough, 3), round(self.metallic, 3), round(self.transmission, 3),
             self.wood, self.kind, self.coat, self.coat_rough, self.sheen, self.sheen_rough, self.subsurface, self.ior, self.contrast, self.tile, self.normal, self.colour]
        return hashlib.sha1(repr(f).encode()).hexdigest()[:8]


def infer_kind(pa, spec: MaterialSpec) -> str | None:
    if spec.kind:
        return ALIASES.get(spec.kind, spec.kind)
    k = pa._scan_kind(spec.name, spec.metallic, spec.wood)          # the legacy name rules first: unchanged behaviour where they hit
    if k:
        return k
    for kind, rx in INFER:
        if re.search(rx, spec.name):
            return kind
    return None


def _phys(m, spec: MaterialSpec, kind: str | None):
    p = dict(PHYS.get(kind, {})) if PHYS_ON else {}
    p.update({k: v for k, v in (("coat", spec.coat), ("coat_rough", spec.coat_rough), ("sheen", spec.sheen),
                               ("sheen_rough", spec.sheen_rough)) if v != MaterialSpec.__dataclass_fields__[k].default})
    b = m.node_tree.nodes["Principled BSDF"]
    for sock, v in (("Coat Weight", p.get("coat")), ("Coat Roughness", p.get("coat_rough") if p.get("coat") else None),
                    ("Sheen Weight", p.get("sheen")), ("Sheen Roughness", p.get("sheen_rough") if p.get("sheen") else None),
                    ("Subsurface Weight", spec.subsurface or None), ("IOR", spec.ior)):
        if v is not None and sock in b.inputs:
            b.inputs[sock].default_value = v


#: A/B arm values (IR_MATSPEC_SCAN=1): stronger scan read on the kinds the user marked 'flat' (tops, upholstery, wood chairs)
SCAN_PUSH = {"wood": {"contrast": 0.9}, "laminate": {"contrast": 0.5}, "fabric": {"contrast": 0.9, "tile": 0.25}}
#: IR_MATSPEC_SCAN=2 (arm 4): arm 3 plus a stronger normal map, a smaller tile on wood / laminate, and the scan's own colour variation on
#: fabric. Metal and paint stay as they are (the lockers already read 'too much texture').
SCAN_PUSH2 = {"wood": {"contrast": 0.9, "tile": 0.5, "normal": 1.4}, "laminate": {"contrast": 0.5, "tile": 0.5, "normal": 1.4},
              "fabric": {"contrast": 0.9, "tile": 0.25, "normal": 1.4, "colour": 0.5}}
SCAN_MODE = os.environ.get("IR_MATSPEC_SCAN", "")
SCAN_ON = SCAN_MODE in ("1", "2")


def _scan_post(pa, m, normal, colour):
    """After pa._scan built its graph: set the normal-map strength; mix the scan's colour (relative to its mean) into the grey variation."""
    nt = m.node_tree
    if normal is not None:
        for n in nt.nodes:
            if n.type == "NORMAL_MAP":
                n.inputs["Strength"].default_value = normal
    if colour:
        bc = next((n for n in nt.nodes if n.type == "TEX_IMAGE" and n.image is not None and "base_color" in n.image.filepath), None)
        mul = next((n for n in nt.nodes if n.type == "MIX" and n.blend_type == "MULTIPLY" and n.inputs[7].is_linked
                    and n.inputs[7].links[0].from_node.type == "COMBINE_COLOR"), None)
        if bc is None or mul is None:
            return
        grey = mul.inputs[7].links[0].from_socket
        mean = pa._SCAN_MEAN.get(bc.image.filepath, 1.0) or 1.0
        rel = nt.nodes.new("ShaderNodeVectorMath"); rel.operation = "SCALE"; rel.inputs["Scale"].default_value = 1.0 / mean
        nt.links.new(bc.outputs["Color"], rel.inputs[0])
        mix = nt.nodes.new("ShaderNodeMix"); mix.data_type = "RGBA"; mix.blend_type = "MIX"; mix.inputs["Factor"].default_value = colour
        nt.links.new(grey, mix.inputs[6]); nt.links.new(rel.outputs[0], mix.inputs[7])
        nt.links.new(mix.outputs[2], mul.inputs[7])


def _scan_with(pa, spec: MaterialSpec, m, kind, name):
    """pa._scan with this spec's contrast / tile for the call (its tables are module globals, restored after)."""
    push = dict((SCAN_PUSH2 if SCAN_MODE == "2" else SCAN_PUSH).get(kind, {})) if SCAN_ON else {}
    push.update({k: v for k, v in (("contrast", spec.contrast), ("tile", spec.tile), ("normal", spec.normal), ("colour", spec.colour))
                 if v is not None})
    old_c, old_t = pa.SCAN_CONTRAST.get(kind), pa.SCAN_TILE.get(kind)
    if "contrast" in push:
        pa.SCAN_CONTRAST[kind] = push["contrast"]
    if "tile" in push:
        pa.SCAN_TILE[kind] = push["tile"]
    try:
        ok = pa._scan(m, spec.rgb, spec.rough, kind, name)
        if ok:
            _scan_post(pa, m, push.get("normal"), push.get("colour"))
        return ok
    finally:
        for tab, k, v in ((pa.SCAN_CONTRAST, kind, old_c), (pa.SCAN_TILE, kind, old_t)):
            tab.pop(k, None) if v is None else tab.__setitem__(k, v)


def build(pa, name, rgb, rough, metallic=0.0, transmission=0.0, wood=False, **phys):
    """proc_assets._flat with a spec. `phys` may carry kind, coat, coat_rough, sheen, sheen_rough, subsurface, ior."""
    spec = MaterialSpec(name, tuple(rgb), rough, metallic, transmission, wood, **phys)
    key = spec.key()
    m = bpy.data.materials.get(name)
    if m is not None and m.get("ir_spec_key") in (None, key):       # a legacy-made material (no key) keeps its name, as before
        return m
    if m is not None:
        name = f"{name}.{key}"
        m = bpy.data.materials.get(name)
        if m is not None:
            return m
    m = bpy.data.materials.new(name); m.use_nodes = True; m["ir_spec_key"] = key
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*spec.rgb, 1); b.inputs["Roughness"].default_value = rough
    b.inputs["Metallic"].default_value = metallic
    if transmission:
        b.inputs["Transmission Weight"].default_value = transmission
    kind = infer_kind(pa, spec)
    if transmission or not pa.SURFACE_DETAIL:
        if wood:
            pa._grain(m, spec.rgb)
    elif not (kind and _scan_with(pa, spec, m, kind, name)):
        pa._grain(m, spec.rgb) if wood else pa._detail(m, spec.rgb, rough, metallic, name)
    _phys(m, spec, kind)
    return m
