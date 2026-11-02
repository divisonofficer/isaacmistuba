"""Run inside Blender 4.2: replace the room shells' wall / floor / ceiling materials of an Infinigen 1.x scene.blend with
Infinigen 2.0 ones (wall_material_rand, floor_material_rand, ceiling_material_rand), deterministically from a seed.

    blender --background IN.blend --python rematerial_rooms_infinigen2.py -- --out OUT.blend --seed N [--site DIR]

Ceilings are left as they are (shader_invisible in Infinigen 1.x; the IR pipeline caps and lights rooms itself).
Tested 2026-10-08 on 62912187: the production bake accepted it (ok, 233 min vs 223, no exclusions) and the baked
atlases keep the patterns (tiles, plaster, carpet).

The 2.0 shaders read metre-scale UVs from a new map "m_uv" (planar per face by its dominant normal axis, as 2.0's own rooms do);
the object's existing UV maps and their active/render flags are left alone, so a later bake still sees what it saw before.
"""
import argparse
import math, json, os, re, sys, time
argv = sys.argv[sys.argv.index("--") + 1:]
ap = argparse.ArgumentParser(); ap.add_argument("--out", required=True); ap.add_argument("--seed", type=int, required=True)
ap.add_argument("--venue", default="", help="cafe | grocery: finishes for a relabelled single-room layout")
ap.add_argument("--style", default="", help="venue style preset name (room_planner/styles.py) or a reference spec .json")
ap.add_argument("--site", default=os.environ.get("INFINIGEN2_SITE", "/root/robomituba-envs/infinigen2-2.0.0a2-site"),
                help="pip --target dir holding infinigen 2.0.0a2, procfunc 0.35.1 and numpy 1.26 (Blender 4.2 ships numpy 1.24)")
a = ap.parse_args(argv)
sys.path.insert(0, a.site)
import bpy
import numpy as np
import procfunc as pf
from infinigen2.shaders import functionality_lists as fl
from infinigen2.shaders.composites import tiles

t0 = time.time()
PAT = re.compile(r"^(?P<room>[a-z-]+_\d+/\d+)\.(?P<part>wall|floor)$")   # ceilings stay shader_invisible: the IR pipeline lights and caps rooms itself
FNS = {"wall": fl.wall_material_rand, "floor": fl.floor_material_rand, "ceiling": fl.ceiling_material_rand}
# 2.0 has one wall list for every room; a bathroom with wood-plank walls reads wrong (user 2026-10-13). Wet rooms get tiles/paint.
WET_ROOMS = {"bathroom", "restroom"}


def wet_wall(rng, vec):
    rng_choice, rng_func = rng.spawn(2)
    return pf.control.choice(rng_choice, [(tiles.tile_indoor_wall_rand, 2.0), (fl.paint_wall_rand, 1.0)])(rng_func, vec)


WET_FNS = {"wall": wet_wall, "floor": tiles.tile_indoor_ground_rand}
# a commercial restroom (floor scenes, 2026-10-16): pale paint and plain light floor -- the random wall tile gave a pink diagonal
# tile in the dental floor's restroom
# tiled, with a fixed neutral ceramic: painted plaster and the office floor read as 'an office with a toilet in it' (floors A2/G/H r4-r8,
# 3 of 3 each); the random tile material gave a pink diagonal (floor E), so the tile colour is pinned and only the pattern varies
from infinigen2.shaders.base_materials import ceramic as _ceramic  # noqa: E402
from infinigen2.shaders.masks import tile_shapes as _shapes  # noqa: E402


def _plain_tile(rgb, per_m, rough=0.3, grout_rgb=None, border=0.04, sub=1.0):
    """Plain square ceramic tile, straight grid: the random pattern gave cube / circle motifs that read as a decorative home bathroom
    (floor F3 r5, coherence 6, 3 of 3)."""
    def fn(rng, vec):
        tv = _shapes.tile_coord_transform_rand(rng, vec, rotation_deg=0.0, scale=per_m, flip=1.0)
        mask = _shapes.square(vector=tv, subtiles_number=sub, aspect_ratio=1.0, border=border, flatness=0.92)
        gr = _ceramic.ceramic(vec, grout_rgb, roughness=0.8) if grout_rgb else None           # a light grout in the tile's own tone (O4 r7: 'white with thick dark grout, not beige stone')
        return tiles.tile_indoor_wall_rand(rng, vec, tile=_ceramic.ceramic(vec, rgb, roughness=rough), grout=gr, tile_mask=mask, scale=per_m)
    return fn


WET_FNS_WORK = {"wall": _plain_tile((0.86, 0.87, 0.86), 6.7), "floor": _plain_tile((0.42, 0.44, 0.45), 4.0, rough=0.4)}
# a café / shop customer WC: deep green wall tile and a dark floor -- the clinic white read as 'a clinical test box, fixtures vanish into
# the walls' (floor G r28: coherence 6, 3 of 3)
WET_FNS_SHOP = {"wall": _plain_tile((0.2, 0.36, 0.3), 6.7, rough=0.2), "floor": _plain_tile((0.16, 0.16, 0.17), 4.0, rough=0.4)}

# hotel bathrooms (H3 r14 SRF-01): the random wall tile drew dark diagonal tiles where the reference has large pale beige stone: ROOM_BATH_STONE="r,g,b" pins a large-format stone tile for room type 'bathroom'
import os as _os  # noqa: E402
_bs = _os.environ.get("ROOM_BATH_STONE")
_bg = _os.environ.get("ROOM_BATH_GLAZED")      # "r,g,b": a glazed 30 x 60 cm wall tile (subtiles 0.5 = a tile twice as long as wide), roughness 0.12, thin light grout (P2b r33); the floor stays the ROOM_BATH_STONE / default one
WET_FNS_GLAZED = ({"wall": _plain_tile(tuple(float(v) for v in _bg.split(",")), 3.3, rough=0.12, grout_rgb=tuple(0.9 * float(v) for v in _bg.split(",")), border=0.008, sub=0.5), "floor": tiles.tile_indoor_ground_rand} if _bg else None)
WET_FNS_STONE = ({"wall": _plain_tile(tuple(float(v) for v in _bs.split(",")), 2.0, rough=0.25, grout_rgb=tuple(0.88 * float(v) for v in _bs.split(",")), border=0.012), "floor": _plain_tile(tuple(0.95 * float(v) for v in _bs.split(",")), 1.7, rough=0.3, grout_rgb=tuple(0.82 * float(v) for v in _bs.split(",")), border=0.012)} if _bs else None)

# Workplaces stand on concrete (a carpet-patterned warehouse read wrong, user 2026-10-16); half get a scratch/splat overlay.
WORK_ROOMS = {"warehouse", "garage", "utility"}


def work_floor(rng, vec):
    from infinigen2.shaders.base_materials import concrete
    rng_choice, rng_func = rng.spawn(2)
    return pf.control.choice(rng_choice, [(lambda r, v: concrete.concrete_rand(r, v), 1.0),
                                          (lambda r, v: fl._layer_rand(r, v, concrete.concrete_rand(r, v)), 1.0)])(rng_func, vec)


def work_wall(rng, vec):
    """Painted block or bare concrete (warehouse r1 critic: OSB wainscot and a smooth grey paint read as a garage or den)."""
    from infinigen2.shaders.base_materials import concrete
    rng_choice, rng_func = rng.spawn(2)
    return pf.control.choice(rng_choice, [(_paint((0.8, 0.8, 0.78)), 2.0), (_paint((0.62, 0.66, 0.7)), 1.0),
                                          (_paint((0.72, 0.7, 0.64)), 1.0)])(rng_func, vec)   # r3: concrete_rand read as stucco


WORK_FNS = {"wall": work_wall, "floor": work_floor}

# Offices get painted walls (a dark mottled stone break room read wrong, user 2026-10-16): paint mostly, sometimes a wood-plank or
# smooth-concrete feature wall; no granite/gravel/flaked/patterned. Floors: carpet, wood planks or plain tiles.
OFFICE_ROOMS = {"office", "open-office", "meeting-room", "break-room", "factory-office", "hallway"}   # a floor's corridor:
# painted like its offices, not the home wall list (floor B r9: 'crumpled-paper stucco', coherence 5, 3 of 3)


def office_wall(rng, vec):
    """Commercial interior paint (user 2026-10-16: wallpaper and coloured walls read as a house): warm white, off-white, light grey;
    the architecture pass adds the charcoal accent wall."""
    rng_choice, rng_func = rng.spawn(2)
    return pf.control.choice(rng_choice, [(_paint((0.87, 0.86, 0.83)), 2.0), (_paint((0.82, 0.82, 0.8)), 2.0),
                                          (_paint((0.68, 0.69, 0.69)), 1.0)])(rng_func, vec)


def office_floor(rng, vec):
    """~70% carpet tile, 30% polished concrete; no wood (critic r1 2026-10-16: a wood-plank meeting room read as a dining room)."""
    rng_choice, rng_func = rng.spawn(2)
    return pf.control.choice(rng_choice, [(fl.carpet.carpet_rand, 7.0), (fl.concrete.concrete_rand, 3.0)])(rng_func, vec)


OFFICE_FNS = {"wall": office_wall, "floor": office_floor}
_SHARED_FLOOR = {}


def cafe_wall(rng, vec):
    from infinigen2.shaders.composites import bricks
    rng_choice, rng_func = rng.spawn(2)
    return pf.control.choice(rng_choice, [(_bricks, 2.5), (bricks.bricks_paint_rand, 1.0), (fl.wood_planks.wood_planks_rand, 1.5),
                                          (fl.paint_wall_rand, 2.0), (tiles.tile_indoor_wall_rand, 0.5)])(rng_func, vec)


def cafe_floor(rng, vec):
    rng_choice, rng_func = rng.spawn(2)
    return pf.control.choice(rng_choice, [(fl.wood_planks.wood_planks_rand, 3.0), (tiles.tile_indoor_ground_rand, 1.5),
                                          (fl.concrete.concrete_rand, 1.0)])(rng_func, vec)


def _pick(*options):
    def fn(rng, vec):
        rng_choice, rng_func = rng.spawn(2)
        return pf.control.choice(rng_choice, list(options))(rng_func, vec)
    return fn


def _bricks(rng, vec):
    """Exposed red brick (user 2026-10-16: 'the brick-brick cafes disappeared'): bricks_rand mostly gives grey/painted/cobble walls."""
    from infinigen2.shaders.composites import bricks
    rng_choice, _ = rng.spawn(2)
    return pf.control.choice(rng_choice, [(lambda r, v: bricks.bricks_red_preset(v), 3.0), (lambda r, v: bricks.bricks_red_concave_preset(v), 2.0),
                                          (lambda r, v: bricks.brick_masonry_brown_preset(v), 1.0)])(rng, vec)


def _paint(rgb):
    def fn(rng, vec):
        return fl.paint.paint_rand(rng, vec, displacement_pct=0.15, base_color=pf.Color(tuple(rgb)))
    return fn


def style_walls(st):
    """A style's (or reference spec's) wall finish: paint in its colour, brick, concrete, wood panel or tile."""
    finish = st.get("wall", "paint")
    if finish == "paint":
        return _paint(st.get("wall_rgb") or (0.85, 0.83, 0.78))
    return {"brick": _bricks, "concrete": fl.concrete.concrete_rand, "wood_panel": fl.wood_planks.wood_planks_rand,
            "tile": tiles.tile_indoor_wall_rand}[finish]


STYLE_FLOORS = {"wood": fl.wood_planks.wood_planks_rand, "concrete": fl.concrete.concrete_rand, "tile": tiles.tile_indoor_ground_rand}

#: --venue relabels a single-room layout (plan_scene --venue): its rooms get that venue's finishes
VENUE_FNS = {"cafe": {"wall": cafe_wall, "floor": cafe_floor},
             "grocery": {"wall": _paint((0.88, 0.88, 0.86)), "floor": tiles.tile_indoor_ground_rand},   # a sales floor, not a stockroom
             "break-room": {"wall": office_wall, "floor": fl.concrete.concrete_rand},
             # non-home 20 (2026-10-16): clinics pale and washable, sales floors white and tiled, boutiques warm
             # clinics: pale sheet vinyl (clinic r1: random tile gave burgundy hexagons and green marble); sales floors: tile
             **{k: {"wall": _paint(c), "floor": _paint(f)} for k, c, f in (
                 ("clinic-reception", (0.9, 0.92, 0.92), (0.72, 0.74, 0.73)), ("exam-room", (0.88, 0.92, 0.93), (0.78, 0.8, 0.8)),
                 ("dental-room", (0.85, 0.92, 0.93), (0.74, 0.78, 0.79)), ("physio-room", (0.9, 0.91, 0.88), (0.62, 0.66, 0.68)))},
             **{k: {"wall": _paint(c), "floor": _paint(f)} for k, c, f in (       # commercial vinyl (shop r1: a pink patterned tile)
                 ("convenience", (0.9, 0.9, 0.88), (0.62, 0.63, 0.63)), ("pharmacy", (0.92, 0.94, 0.93), (0.74, 0.76, 0.75)))},
             "boutique": {"wall": _paint((0.9, 0.87, 0.82)), "floor": fl.wood_planks.wood_planks_rand}}   # office pantry: not carpet (r2), not glossy green herringbone tile (r3)


def planar_group():
    """Node group 'm_planar': world position projected on the plane its normal faces most (x->yz, y->xz, z->xy), in metres.
    Computed in the shader so it survives the bake's mesh export, which drops extra UV layers."""
    g = bpy.data.node_groups.get("m_planar")
    if g:
        return g
    g = bpy.data.node_groups.new("m_planar", "ShaderNodeTree")
    g.interface.new_socket("Vector", in_out="OUTPUT", socket_type="NodeSocketVector")
    n = g.nodes; L = g.links
    geo = n.new("ShaderNodeNewGeometry"); out = n.new("NodeGroupOutput")
    sp = n.new("ShaderNodeSeparateXYZ"); L.new(geo.outputs["Position"], sp.inputs[0])
    nabs = n.new("ShaderNodeVectorMath"); nabs.operation = "ABSOLUTE"; L.new(geo.outputs["Normal"], nabs.inputs[0])
    sn = n.new("ShaderNodeSeparateXYZ"); L.new(nabs.outputs[0], sn.inputs[0])
    def cmp(a, b):  # 1 where a >= b
        m = n.new("ShaderNodeMath"); m.operation = "GREATER_THAN"; L.new(a, m.inputs[0]); L.new(b, m.inputs[1]); return m.outputs[0]
    def mx(a, b):
        m = n.new("ShaderNodeMath"); m.operation = "MAXIMUM"; L.new(a, m.inputs[0]); L.new(b, m.inputs[1]); return m.outputs[0]
    x_dom = n.new("ShaderNodeMath"); x_dom.operation = "MULTIPLY"
    L.new(cmp(sn.outputs[0], sn.outputs[1]), x_dom.inputs[0]); L.new(cmp(sn.outputs[0], sn.outputs[2]), x_dom.inputs[1])
    z_dom = cmp(sn.outputs[2], mx(sn.outputs[0], sn.outputs[1]))
    vx = n.new("ShaderNodeCombineXYZ"); L.new(sp.outputs[1], vx.inputs[0]); L.new(sp.outputs[2], vx.inputs[1])   # x-facing: (y, z)
    vy = n.new("ShaderNodeCombineXYZ"); L.new(sp.outputs[0], vy.inputs[0]); L.new(sp.outputs[2], vy.inputs[1])   # y-facing: (x, z)
    vz = n.new("ShaderNodeCombineXYZ"); L.new(sp.outputs[0], vz.inputs[0]); L.new(sp.outputs[1], vz.inputs[1])   # z-facing: (x, y)
    m1 = n.new("ShaderNodeMix"); m1.data_type = "VECTOR"; L.new(x_dom.outputs[0], m1.inputs["Factor"])
    L.new(vy.outputs[0], m1.inputs[4]); L.new(vx.outputs[0], m1.inputs[5])
    m2 = n.new("ShaderNodeMix"); m2.data_type = "VECTOR"; L.new(z_dom, m2.inputs["Factor"])
    L.new(m1.outputs[1], m2.inputs[4]); L.new(vz.outputs[0], m2.inputs[5])
    L.new(m2.outputs[1], out.inputs[0])
    return g


def rewire_to_planar(mat):
    """Feed every input the 'm_uv' UV-map node fed from the m_planar group instead, then drop the UV-map nodes."""
    nt = mat.node_tree; grp = planar_group(); n = 0
    for node in list(nt.nodes):
        if node.bl_idname == "ShaderNodeUVMap" and node.uv_map == "m_uv":
            gn = nt.nodes.new("ShaderNodeGroup"); gn.node_tree = grp
            for link in list(node.outputs[0].links):
                nt.links.new(gn.outputs[0], link.to_socket)
            nt.nodes.remove(node); n += 1
    return n


def level_wall_patterns(mat) -> int:
    """2.0 tile/brick shaders rotate their pattern by k*90 deg (+45 deg 30% of the time): fine on a floor, but bricks on a wall run
    horizontal. Snap every unlinked Mapping rotation to a multiple of 180 deg (rows stay horizontal, the pattern may flip)."""
    n = 0
    for node in mat.node_tree.nodes:
        if node.bl_idname != "ShaderNodeMapping" or node.inputs["Rotation"].is_linked:
            continue
        x, y, z = node.inputs["Rotation"].default_value
        level = (0.0, 0.0, round(z / math.pi) * math.pi)
        if (x, y, z) != level:
            node.inputs["Rotation"].default_value = level
            n += 1
    return n


def kit_finish(name, st):
    """A style-kit wall finish (non-home 20, 2026-10-16: 'a style is the relation between its parts', so every surface reads one kit)."""
    dark = st.get("mood") == "dark_moody" or st.get("floor_tone") == "dark"
    if name == "paint_dark":
        return _paint(st.get("wall_rgb") if st.get("wall_rgb") and sum(st["wall_rgb"]) < 0.6 else (0.045, 0.04, 0.035))
    if name == "paint_feature" and st.get("feature_rgb"):       # a painted accent wall in its own colour (exam room S18: pale-blue wall behind the table)
        return _paint(st["feature_rgb"])
    if name in ("paint_light", "shelving"):
        return _paint(st.get("wall_rgb") if st.get("wall_rgb") and sum(st["wall_rgb"]) >= 0.6 else (0.85, 0.83, 0.78))
    if name == "wood_panel":
        return (lambda r, v: fl.wood_planks.wood_planks_brown_preset(v)) if dark else (lambda r, v: fl.wood_planks.wood_planks_blonde_preset(v))
    if name == "tile":                                          # the random wall-tile shader drew olive swirl mosaics where the refs
        return _paint((0.92, 0.92, 0.9))                        # show plain white tile (style evals I/J); a plain light finish instead
    return {"brick": _bricks, "concrete": fl.concrete.concrete_rand}[name]


def kit_floor(st):
    kind, tone = st.get("floor", "wood"), st.get("floor_tone", "medium")
    if kind == "wood":
        return (lambda r, v: fl.wood_planks.wood_planks_blonde_preset(v)) if tone == "pale" else (lambda r, v: fl.wood_planks.wood_planks_brown_preset(v))
    if kind != "wood" and st.get("floor_rgb"):                # concrete, vinyl, tile: the reference's tone (clinic r6: a random green
        return _paint(st["floor_rgb"])                          # patterned tile where the kit said pale beige tile)
    return STYLE_FLOORS[kind]


def feature_wall_mask(o):
    """Faces of the back wall (the one facing the storefront, y max): inward normal -y, on the farthest such plane."""
    me, mw = o.data, o.matrix_world
    ny = np.array([(mw.to_3x3() @ p.normal).normalized().y for p in me.polygons])
    cy = np.array([(mw @ p.center).y for p in me.polygons])
    back = ny < -0.7
    if not back.any():
        return back
    return back & (cy > cy[back].max() - 0.3)


def finish_floor(mat, rgb, rough, tint=0.0, mottle=0.0):
    """A kit floor's finish (café style evals I/J, all four: 'flat matte beige where the ref has glossy mottled polished concrete';
    'orange high-gloss parquet where the ref has matte pale oak'): every BSDF's colour is pulled `tint` of the way to the kit's floor
    colour and multiplied by a low-frequency noise of +-`mottle`; its roughness is set to `rough` (nested groups included)."""
    if mat is None or not mat.use_nodes:
        return 0
    seen, n = set(), 0
    def walk(nt):
        nonlocal n
        if nt.name in seen:
            return
        seen.add(nt.name)
        for node in list(nt.nodes):
            if node.type == "GROUP" and node.node_tree is not None:
                walk(node.node_tree)
            elif node.type == "BSDF_PRINCIPLED":
                sock = node.inputs["Base Color"]
                src = sock.links[0].from_socket if sock.is_linked else None
                mix = nt.nodes.new("ShaderNodeMix"); mix.data_type = "RGBA"; mix.inputs[0].default_value = tint
                mix.inputs[7].default_value = (*rgb, 1)       # colour sockets by index: "A"/"B" name the float ones first
                if src is not None:
                    nt.links.new(src, mix.inputs[6])
                else:
                    mix.inputs[6].default_value = sock.default_value
                out = mix.outputs[2]
                if mottle:
                    tc = nt.nodes.new("ShaderNodeTexCoord"); nz = nt.nodes.new("ShaderNodeTexNoise")
                    nz.inputs["Scale"].default_value = 1.2; nz.inputs["Detail"].default_value = 6.0
                    mr = nt.nodes.new("ShaderNodeMapRange"); mr.inputs["To Min"].default_value = 1 - mottle; mr.inputs["To Max"].default_value = 1 + mottle
                    mul = nt.nodes.new("ShaderNodeMix"); mul.data_type = "RGBA"; mul.blend_type = "MULTIPLY"; mul.inputs[0].default_value = 1.0
                    nt.links.new(tc.outputs["Object"], nz.inputs["Vector"]); nt.links.new(nz.outputs["Fac"], mr.inputs["Value"])
                    nt.links.new(out, mul.inputs[6]); nt.links.new(mr.outputs["Result"], mul.inputs[7])
                    out = mul.outputs[2]
                nt.links.new(out, sock)
                r_ = node.inputs["Roughness"]
                for l in list(r_.links):
                    nt.links.remove(l)
                r_.default_value = rough
                if rough >= 0.5:                                 # matte: the wood preset's clear coat kept a mirror gloss at roughness 0.6
                    for nm, v in (("Coat Weight", 0.0), ("Specular IOR Level", 0.25)):   # (café K nordic: 'mirror specular highlights')
                        if nm in node.inputs:
                            for l in list(node.inputs[nm].links):
                                nt.links.remove(l)
                            node.inputs[nm].default_value = v
                n += 1
    walk(mat.node_tree)
    return n


def darken(mat, k):
    """Multiply every BSDF colour in a material (nested node groups included) by k: keeps grain and pattern, lowers the tone. The 2.0
    shaders wrap their BSDFs in groups, so a top-level-only edit did nothing (floral_moody s3b: walls stayed orange)."""
    if mat is None or not mat.use_nodes:
        return 0
    seen, n = set(), 0
    def walk(nt):
        nonlocal n
        if nt.name in seen:
            return
        seen.add(nt.name)
        for node in list(nt.nodes):
            if node.type == "GROUP" and node.node_tree is not None:
                walk(node.node_tree)
            elif node.type.startswith("BSDF"):
                for name in ("Base Color", "Color"):
                    if name in node.inputs:
                        sock = node.inputs[name]
                        mix = nt.nodes.new("ShaderNodeMix"); mix.data_type = "RGBA"; mix.blend_type = "MULTIPLY"
                        mix.inputs["Factor"].default_value = 1.0
                        mix.inputs["B"].default_value = (k, k * 0.92, k * 0.85, 1)
                        if sock.is_linked:
                            nt.links.new(sock.links[0].from_socket, mix.inputs["A"])
                        else:
                            mix.inputs["A"].default_value = sock.default_value
                        nt.links.new(mix.outputs["Result"], sock)
                        n += 1
                        break
    walk(mat.node_tree)
    return n


STYLE_FNS = {}
_st_spec = json.load(open(a.style)) if a.style and a.style.endswith(".json") else None
KIT = None
if a.style:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from room_planner import styles as _styles
    _st = json.load(open(a.style)) if a.style.endswith(".json") else _styles.get(a.venue, a.style)   # preset name or spec file
    STYLE_FNS = {"wall": style_walls(_st), "floor": STYLE_FLOORS[_st.get("floor", "wood")]}
    if (a.venue or (_st.get("venue") if isinstance(_st, dict) else None)) in ("open-office", "office", "meeting-room") and \
            _st.get("floor", "wood") == "wood":   # floors pass no --venue: the kit's own (floor C r3: glossy orange planks, 3/3)   # a work floor is carpet tile or
        STYLE_FNS["floor"] = office_floor     # concrete whatever the photo shows (office r8: high-rise parquet 'residential', 3 of 3)
    if isinstance(_st, dict) and _st.get("architecture"):      # a style kit: other walls / feature wall / floor tone together
        KIT = _st
        if _st.get("venue") in ("warehouse", "garage"):         # block/concrete, not plaster (warehouse r9/r11: 'packing reads as an office')
            for k_ in ("other_walls", "feature_wall"):
                if _st["architecture"].get(k_) in ("paint_light", "paint_dark", "shelving"):
                    _st["architecture"][k_] = "concrete"
        if _st.get("venue") in ("clinic-reception", "exam-room", "dental-room", "physio-room") and _st.get("wall_rgb") and \
                not (os.environ.get("ROOM_CLINIC_LOBBY") == "1" and _st.get("venue") == "clinic-reception"):   # the lobby keeps the kit's warm cream
            # walls cooled 85% toward a clinical pale grey-white (clinic r23: the reference's warm tan read as a hotel lobby, 3 of 3).
            # Here, before kit_finish: it bakes the colour into the paint function when called (r24/r25 overrode it after: no effect)
            _st["wall_rgb"] = [round(0.15 * c + 0.85 * w, 4) for c, w in zip(_st["wall_rgb"], (0.74, 0.79, 0.82))]
        STYLE_FNS = {"wall": kit_finish(_st["architecture"]["other_walls"], _st), "floor": kit_floor(_st)}
targets = sorted((o for o in bpy.data.objects if o.type == "MESH" and PAT.match(o.name)), key=lambda o: o.name)
rng = np.random.default_rng(a.seed)
record = []
for o in targets:
    part = PAT.match(o.name).group("part")
    (r,) = rng.spawn(1)
    before = [s.material.name for s in o.material_slots if s.material]
    room_type = PAT.match(o.name).group("room").split("_")[0]
    fns = (WET_FNS_GLAZED if WET_FNS_GLAZED and room_type in _os.environ.get("ROOM_BATH_GLAZED_ROOMS", "bathroom,restroom").split(",") else
           WET_FNS_STONE if WET_FNS_STONE and room_type in _os.environ.get("ROOM_BATH_STONE_ROOMS", "bathroom").split(",") else       # ROOM_BATH_STONE_ROOMS=bathroom,restroom: commercial restrooms too (O4 r6)
           WET_FNS_SHOP if room_type == "restroom" and isinstance(_st_spec, dict) and _st_spec.get("venue") in ("cafe", "convenience", "grocery", "boutique")
           else WET_FNS_WORK if room_type == "restroom" else       # 'restroom' only exists on commercial floors (homes use 'bathroom')
           OFFICE_FNS if room_type in ("office", "break-room") and isinstance(_st_spec, dict) and _st_spec.get("venue") == "warehouse" else
           # a warehouse kit's raw concrete stays in the hall: on the site office and staff room it read as 'water-stained render, an
           # unfinished shell' (floor J r18-r20, 3 of 3 each)
           STYLE_FNS if STYLE_FNS and room_type not in WET_ROOMS else
           VENUE_FNS[a.venue] if a.venue in VENUE_FNS and room_type not in WET_ROOMS else WET_FNS if room_type in WET_ROOMS
           else WORK_FNS if room_type in WORK_ROOMS else OFFICE_FNS if room_type in OFFICE_ROOMS else FNS)
    # one floor finish for every office-type room on a scene (floor B: each private office drew its own carpet -- pink, green
    # stripes -- 'patched together', 3 of 3); the first such room's material is reused
    shared = part == "floor" and fns is OFFICE_FNS and room_type in ("office", "meeting-room", "open-office")
    mat = _SHARED_FLOOR.get("office") if shared else None
    reused = mat is not None                                  # already rewired by its first room: rewire finds no m_uv node
    if mat is None:
        mat = fns[part](r, pf.nodes.shader.uv_map(uv_map="m_uv"))
        if shared:
            _SHARED_FLOOR["office"] = mat
    pf.ops.object.set_material(pf.types.MeshObject(o), material=mat)
    after = [s.material.name for s in o.material_slots if s.material]
    rewired = sum(rewire_to_planar(s.material) for s in o.material_slots if s.material)
    assert rewired > 0 or reused, f"{o.name}: no m_uv node to rewire"
    if KIT is not None and (KIT.get("floor_tone") == "dark" or KIT.get("mood") == "dark_moody") and part in ("wall", "floor"):
        if part == "floor" or KIT["architecture"]["other_walls"] in ("wood_panel",):
            nd = sum(darken(sl.material, 0.32) for sl in o.material_slots)   # dark stained wood, not orange
            print(f"[kit] darkened {o.name}: {nd} BSDFs", flush=True)
    if KIT is not None and part == "floor" and KIT.get("floor_rgb"):
        conc = KIT.get("floor") != "wood"
        frgb = KIT["floor_rgb"]
        if conc:                                                 # concrete is near neutral: the kit reads it beige off a warm-lit photo
            lum = 0.2126 * frgb[0] + 0.7152 * frgb[1] + 0.0722 * frgb[2]   # (café K: 'matte beige, carpet-like' vs grey polished concrete)
            frgb = [0.15 * c + 0.85 * lum for c in frgb]   # 85% (cafe r4: 60% left the industrial concrete 'beige carpet', 3 of 3)
        nf = sum(finish_floor(sl.material, frgb, 0.22 if conc else 0.6, tint=1.0 if conc else 0.55, mottle=0.14 if conc else 0.0)
                 for sl in o.material_slots)
        print(f"[kit] floor finish {'polished concrete' if conc else 'matte tinted wood'}: {nf} BSDFs", flush=True)
    if KIT is not None and KIT.get("venue") in ("clinic-reception", "exam-room", "dental-room", "physio-room", "pharmacy") and KIT["architecture"].get("feature_wall") in ("wood_panel", "brick"):
        KIT["architecture"]["feature_wall"] = "paint_light"      # washable walls in a clinic (clinic r10: wood-plank wall read as a lounge)
    if KIT is not None and part == "wall" and KIT["architecture"]["feature_wall"] != KIT["architecture"]["other_walls"] and \
            room_type not in ("restroom", "utility", "closet", "kitchen", "hallway") and room_type not in WET_ROOMS:
        # the venue's feature wall is front-of-house: a wood-plank wall in the restrooms and stockroom read as 'pieces of the café
        # shell' (floor H r7, 3 of 3) and is no washable surface
        (r2,) = rng.spawn(1)
        fm = kit_finish(KIT["architecture"]["feature_wall"], KIT)(r2, pf.nodes.shader.uv_map(uv_map="m_uv"))
        mask = feature_wall_mask(o)
        if mask.any():
            pf.ops.object.set_material(pf.types.MeshObject(o), material=fm, selection=mask)
            rewire_to_planar(o.material_slots[-1].material)
        print(f"[kit] feature wall {KIT['architecture']['feature_wall']}: {int(mask.sum())} faces", flush=True)
    leveled = sum(level_wall_patterns(s.material) for s in o.material_slots if s.material) if part == "wall" else 0
    record.append({"object": o.name, "part": part, "before": before, "after": after, "rewired_uv_nodes": rewired,
                   "leveled_mappings": leveled})
bpy.ops.wm.save_as_mainfile(filepath=a.out, copy=True)
json.dump({"seed": a.seed, "objects": record, "seconds": round(time.time() - t0, 1), "generator": "infinigen 2.0.0a2 functionality_lists"},
          open(a.out + ".rematerial.json", "w"), indent=1)
print("REMATERIAL", len(record), "objects in", round(time.time() - t0, 1), "s", flush=True)
