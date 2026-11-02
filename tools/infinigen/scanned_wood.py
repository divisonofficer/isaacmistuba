"""Scanned-wood material builder (user 10-24: 'S31 wood texture realism', 'S32 chair / table texture realism'; also P1 of the realism program). Reusable by any scene:

    import scanned_wood as sw
    mat = sw.material("oak_plank", size_m=1.2, tint=(1, 1, 1), rough=(0.35, 0.6), coat=0.0, space="world")   # a Principled material, cached by its arguments
    sw.apply(stats)                                                                                          # kit pass, ROOM_SCAN_WOOD=1: every wood-like material slot -> a scanned wood by role

Textures: TextureCan sets (base_color / roughness / normal_gl) from /bean/ir_pbr_assets/texturecan_environment_merged_v1. Mapping: BOX projection of the Geometry Position (space="world", metres: floors, ceilings, beams
-- continuous across objects, no UVs needed) or the Object coordinate (space="object": furniture, grain follows the piece). Everything goes through Principled inputs, so albedo / roughness / normal GT channels carry it:
  base colour   scan albedo x tint x a per-object value / hue jitter (Object Info Random, +-6 % value, +-1.5 % hue)
  roughness     the scan's roughness remapped to `rough` (lo, hi)
  normal        the scan's normal map (strength ROOM_SCAN_WOOD_NORMAL, default 0.9)
  coat          clear coat on tables (coat > 0)
Presets: oak_plank (0056 clean planks), oak_dark (0038 rustic boards), walnut (0061), beam (0049 rough timber with cracks), ash (0054 light grain), ebony (0035), pine_knot (0055), herring_dark (0040), herring_black (0043),
chevron_light (0042), plank_light (0037).

apply() env:  ROOM_SCAN_WOOD=1
  ROOM_SCAN_WOOD_ROLES="chair:oak_dark,table:oak_plank,beam:beam,floor:herring_dark"   role -> preset (default chair:oak_dark, table:oak_plank, counter:ash, beam:beam, panel:oak_plank; no floor unless listed)
  ROOM_SCAN_WOOD_SIZE="floor:1.2,beam:1.6"  metres per texture tile (default 1.0; beams 1.5, floors 1.2)
  ROOM_SCAN_WOOD_TINT="r,g,b" multiplies every scanned albedo (a dark stain over the scan)       ROOM_SCAN_WOOD_COAT=0.35 clear coat weight on tables / counters
  ROOM_SCAN_WOOD_ONLY="Chair,Stool"  object-name prefixes that get it (default: all roles)       ROOM_SCAN_WOOD_BEVEL=0.002  edge bevel (m) on chairs / tables (0 = off)
Idempotent: slots already holding a scanned_wood material are skipped."""
from __future__ import annotations

import os
import re

import bpy

ROOT = "/bean/ir_pbr_assets/texturecan_environment_merged_v1/texturecan/texturecan_wood_"
PRESETS = {"oak_plank": "0056", "oak_dark": "0038", "walnut": "0061", "beam": "0049", "ash": "0054", "ebony": "0035", "pine_knot": "0055", "herring_dark": "0040", "herring_black": "0043",
           "chevron_light": "0042", "plank_light": "0037"}
WOODISH = re.compile(r"slat_wall|panel_wall|wood|oak|timber|plank|walnut|veneer|butcher|parquet|birch|ash_|stool_oak|brk_oak|cafe_oak|ramen_oak|lp_wood|slat_wall|panel_wall|material\.hb|herring|beam|rafter", re.I)
ROLES_DEFAULT = {"chair": "oak_dark", "table": "oak_plank", "counter": "ash", "beam": "beam", "panel": "oak_plank", "ceiling": "oak_plank"}      # "door" is opt-in (ROOM_SCAN_WOOD_ROLES=...,door:oak_plank): door leaves + casings
KEYS = {"door": ("Door", "Casing"), "chair": ("Chair", "Stool", "Bench"), "table": ("Table", "Desk", "Shelf", "Bookcase", "Cabinet", "Sideboard", "Credenza", "Wardrobe", "Vanity"), "counter": ("Counter", "Bar"),
        "beam": ("Beam", "Rafter", "Timber", "Ceiling"), "panel": ("Panel", "Slat", "Wall")}
SIZE = {"floor": 1.2, "beam": 1.5, "door": 0.9}
DOORMAT = re.compile(r"door_leaf|door_frame|flush_leaf|leaf|casing|door", re.I)
NOTDOOR = re.compile(r"glass|chrome|steel|handle|brass|kick|lever|metal|plate", re.I)


def _img(path, nc):
    im = bpy.data.images.load(path, check_existing=True)
    im.colorspace_settings.name = "Non-Color" if nc else "sRGB"
    return im


def material(preset="oak_plank", size_m=1.0, tint=(1.0, 1.0, 1.0), rough=(0.35, 0.6), coat=0.0, space="world", jitter=0.06, grain="x"):
    key = f"scanned_wood_{preset}_{os.environ.get('ROOM_SCAN_WOOD_SAT', '1')}_{size_m:g}_{'_'.join(f'{t:.2f}' for t in tint)}_{rough[0]:g}_{rough[1]:g}_{coat:g}_{space}_{grain}"
    m = bpy.data.materials.get(key)
    if m is not None:
        return m
    d = ROOT + PRESETS[preset]
    m = bpy.data.materials.new(key); m.use_nodes = True; nt = m.node_tree; N, L = nt.nodes, nt.links; b = N["Principled BSDF"]
    if space == "world":
        src = N.new("ShaderNodeNewGeometry"); vec = src.outputs["Position"]
    else:
        src = N.new("ShaderNodeTexCoord"); vec = src.outputs["Object"]
    mp = N.new("ShaderNodeMapping"); mp.inputs["Scale"].default_value = (1 / size_m, 1 / size_m, 1 / size_m); L.new(vec, mp.inputs["Vector"])
    if grain == "z":                                                                            # grain along the vertical (chair legs and uprights): the scan's x axis -> z
        mp.inputs["Rotation"].default_value = (0.0, 1.5708, 0.0)
    elif grain == "y":                                                                          # grain along the object's y (a counter / table whose long side is local y)
        mp.inputs["Rotation"].default_value = (0.0, 0.0, 1.5708)

    def tex(path, nc):
        t = N.new("ShaderNodeTexImage"); t.image = _img(path, nc); t.projection = "BOX"; t.projection_blend = 0.15; t.interpolation = "Smart"; t.extension = "REPEAT"
        L.new(mp.outputs["Vector"], t.inputs["Vector"]); return t
    tb, tr, tn = tex(d + "/base_color.jpg", False), tex(d + "/roughness.jpg", True), tex(d + "/normal_gl.png", True)
    info = N.new("ShaderNodeObjectInfo")
    hs = N.new("ShaderNodeHueSaturation")
    hs.inputs["Saturation"].default_value = float(os.environ.get("ROOM_SCAN_WOOD_SAT") or 1.0)                  # <1: a paler, less orange wood (S36 r2 floor)                                                       # per-object tone: value +-jitter, hue +-1.5 %
    rv = N.new("ShaderNodeMapRange"); rv.inputs["To Min"].default_value = 1 - jitter; rv.inputs["To Max"].default_value = 1 + jitter; L.new(info.outputs["Random"], rv.inputs["Value"]); L.new(rv.outputs["Result"], hs.inputs["Value"])
    rh = N.new("ShaderNodeMapRange"); rh.inputs["To Min"].default_value = 0.485; rh.inputs["To Max"].default_value = 0.515; L.new(info.outputs["Random"], rh.inputs["Value"]); L.new(rh.outputs["Result"], hs.inputs["Hue"])
    L.new(tb.outputs["Color"], hs.inputs["Color"])
    mx = N.new("ShaderNodeMix"); mx.data_type = "RGBA"; mx.blend_type = "MULTIPLY"; mx.inputs["Factor"].default_value = 1.0; mx.inputs[7].default_value = (*tint, 1.0); L.new(hs.outputs["Color"], mx.inputs[6])
    L.new(mx.outputs[2], b.inputs["Base Color"])
    rr = N.new("ShaderNodeMapRange"); rr.inputs["To Min"].default_value = rough[0]; rr.inputs["To Max"].default_value = rough[1]; L.new(tr.outputs["Color"], rr.inputs["Value"]); L.new(rr.outputs["Result"], b.inputs["Roughness"])
    nm = N.new("ShaderNodeNormalMap"); nm.inputs["Strength"].default_value = float(os.environ.get("ROOM_SCAN_WOOD_NORMAL") or 0.9); L.new(tn.outputs["Color"], nm.inputs["Color"]); L.new(nm.outputs["Normal"], b.inputs["Normal"])
    if coat > 0 and "Coat Weight" in b.inputs:
        b.inputs["Coat Weight"].default_value = coat; b.inputs["Coat Roughness"].default_value = 0.08
    m["scanned_wood"] = preset; m["weathered"] = True
    b["weathered"] = True                                                                        # weather_pass must not dirty a scan twice
    return m


def _role(o):
    n = o.name.split("(")[0]
    if o.name.endswith(".floor"):
        return "floor"
    if o.name.endswith(".wall") and any(sl.material and sl.material.name in ("ir_late_slat_wall", "ir_late_panel_wall") for sl in o.material_slots):
        return "panel"                                                                           # H3: the oak slat headboard wall (late_walls) is a .wall mesh; its slot is the 'panel' role
    if o.name.endswith(".ceiling"):                                                              # a timber ceiling (S31): only its wood-named slots are touched
        return "ceiling"
    for role in ("door", "chair", "counter", "table", "beam", "panel"):                                   # chair before table: 'Bench' vs 'Workbench' ... first hit wins
        if any(k in n for k in KEYS[role]):
            return role
    return None


def apply(stats):
    roles = dict(ROLES_DEFAULT)
    for kv in (os.environ.get("ROOM_SCAN_WOOD_ROLES") or "").split(","):
        if ":" in kv:
            r, p = kv.split(":", 1); roles[r.strip()] = p.strip()
    sizes = dict(SIZE)
    for kv in (os.environ.get("ROOM_SCAN_WOOD_SIZE") or "").split(","):
        if ":" in kv:
            r, v = kv.split(":", 1); sizes[r.strip()] = float(v)
    tint = tuple(float(x) for x in (os.environ.get("ROOM_SCAN_WOOD_TINT") or "1,1,1").split(","))
    coat = float(os.environ.get("ROOM_SCAN_WOOD_COAT") or 0.0)
    only = tuple(x for x in (os.environ.get("ROOM_SCAN_WOOD_ONLY") or "").split(",") if x)
    bevel = float(os.environ.get("ROOM_SCAN_WOOD_BEVEL") or 0.0)
    force = tuple(x for x in (os.environ.get("ROOM_SCAN_WOOD_FORCE") or "").split(",") if x)          # roles whose slots are replaced whatever the material is called (S36: the floor material is just "material")
    n = 0; nb = 0
    for o in bpy.data.objects:
        if o.type != "MESH" or (o.parent is not None and _role(o.parent) is None and _role(o) is None):
            continue
        if only and not o.name.startswith(only):
            continue
        role = _role(o)
        if role is None or role not in roles:
            continue
        hit = False
        for sl in o.material_slots:
            mt = sl.material
            if mt is None or mt.get("scanned_wood") or not (role in force or WOODISH.search(mt.name) or (role == "door" and DOORMAT.search(mt.name) and not NOTDOOR.search(mt.name))):
                continue
            if role == "door" and NOTDOOR.search(mt.name):
                continue
            if mt.name.startswith("scanned_wood"):
                continue
            space = "world" if role in ("floor", "beam", "panel", "ceiling") else "object"
            sl.material = material(roles[role], sizes.get(role, 1.0), tint, rough=(0.3, 0.55) if role in ("table", "counter") else (0.4, 0.7), coat=coat if role in ("table", "counter") else 0.0, space=space, grain="z" if (role == "chair" or "Wardrobe" in o.name or (role in ("door", "table") and o.dimensions[2] > 1.3 * max(o.dimensions[0], o.dimensions[1]))) else (("y" if o.dimensions[1] > o.dimensions[0] else "x") if role in ("table", "counter", "door") else "x"))
            n += 1; hit = True
        if hit and bevel > 0 and role in ("chair", "table", "counter") and not any(md.type == "BEVEL" for md in o.modifiers) and len(o.data.polygons) < 20000:
            md = o.modifiers.new("ir_wood_bevel", "BEVEL"); md.width = bevel; md.segments = 2; md.limit_method = "ANGLE"; md.angle_limit = 0.6; nb += 1
    stats["scanned_wood"] = {"slots": n, "bevelled": nb}
    return n
