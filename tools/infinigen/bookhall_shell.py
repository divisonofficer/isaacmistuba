"""B3 bookHall_01 kit-stage shell (large high-ceilinged open bookstore hall, 40 x 26 m, ceiling 7.56 m; user 2026-10-25). ROOM_BOOKHALL_SHELL=1; ROOM_BOOKHALL_SKIP=<comma list of parts>;
ROOM_BOOKHALL_LIGHT = light gain (default 1.0). Idempotent via scene["ir_bookhall_shell"]; every part is isolated (try/except) and reports STATS.
Everything is built from data/venue_refs/bookstore_hall_01/refs_clean/layout_spec.json (frame: x east, y north, origin = the room's SW corner; the room box is 0..40 x 0..26), so the shell does NOT need the
ROOM_BOOKSTORE row layout (84 islands + a veneer ceiling): `clean` removes those pieces and the shell re-furnishes the hall.
Parts: clean facade floor ceiling columns mezz towers gondolas islands cafe pegs steps checkout lamps plants gallery perimeter backdrop details light
  floor     honey oak basket-weave parquet with board-level colour and sheen variation
  ceiling   oak egg-crate lattice at the true height (0.45 m cells, 0.3 m deep, main beams every 4.5 m) with recessed downlights
  columns   6 white round columns (r 0.35) at the spec positions
  mezz      west gallery slab at z 4.0-4.2 (x 0-5) with a glass balustrade + brass rail on its x = 5 edge, downlights underneath
  towers    5 full-height (7 m) oak shelving towers, 2 faces of cubbies, LED strip under every board, tidy face-out books (atlas covers)
  gondolas  9 black steel-frame double-sided book gondolas, 4 oak shelves per side with price rail, face-out book rows leaning back, under-shelf LED
  islands   3 low oak display islands with lit cubbies, tidy book piles on top, brass dome lamp
  cafe      stone/oak counter, HSSD coffee equipment, two four-seat oak/leather table groups, service backbar and pastry display
  pegs      3 low double-sided stationery islands with real-size notebook stacks
  steps     4 connected oak tiers with three long sage benches, six reading tables, cube seats and book cubbies
  checkout  oak counter with stone top, HSSD monitor
  lamps     5 cream drum floor lamps (lit)
  plants    large HSSD plants
  light     warm 3000 K area fill over the hall (ROOM_BOOKHALL_LIGHT)
"""
from __future__ import annotations

import json
import math
import os
import random

import bpy
import bmesh
from mathutils import Matrix, Vector

SPEC = "/jarvis/project/robomituba/data/venue_refs/bookstore_hall_01/refs_clean/layout_spec.json"
ROOM = "break-room_0/0"
W, D = 40.0, 26.0
LIGHT = float(os.environ.get("ROOM_BOOKHALL_LIGHT") or 1.0)
_S = {}


def _fl():
    from room_planner import proc_boutique_flagship as fl
    return fl


def _pa():
    from room_planner import proc_assets as pa
    return pa


def _flat(name, rgb, rough=0.5, metal=0.0, **kw):
    m = _pa()._flat(name, rgb, rough, metal, **kw); m["weathered"] = True
    return m


def _emit(name, rgb, s):
    m = _flat(name, rgb, 0.4); b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Emission Color"].default_value = (*rgb, 1.0); b.inputs["Emission Strength"].default_value = s
    return m


def _oak(name="ir_bh_oak", rgb=(0.62, 0.40, 0.2)):
    m = bpy.data.materials.get(name)
    if m is not None:
        return m
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    m["weathered"] = True
    N, L = m.node_tree.nodes, m.node_tree.links
    bs = N["Principled BSDF"]
    bs.inputs["Roughness"].default_value = 0.40
    tc = N.new("ShaderNodeTexCoord")
    stretch = N.new("ShaderNodeVectorMath")
    stretch.operation = "MULTIPLY"
    stretch.inputs[1].default_value = (1.1, 38.0, 3.0)
    grain = N.new("ShaderNodeTexNoise")
    grain.inputs["Scale"].default_value = 3.5
    grain.inputs["Detail"].default_value = 3.0
    L.new(tc.outputs["Object"], stretch.inputs[0])
    L.new(stretch.outputs["Vector"], grain.inputs["Vector"])
    mix = N.new("ShaderNodeMixRGB")
    mix.inputs[1].default_value = (*rgb, 1.0)
    mix.inputs[2].default_value = (*(v * 0.78 for v in rgb), 1.0)
    L.new(grain.outputs["Fac"], mix.inputs[0])
    L.new(mix.outputs[0], bs.inputs["Base Color"])
    bump = N.new("ShaderNodeBump")
    bump.inputs["Distance"].default_value = 0.00025
    bump.inputs["Strength"].default_value = 0.16
    L.new(grain.outputs["Fac"], bump.inputs["Height"])
    L.new(bump.outputs["Normal"], bs.inputs["Normal"])
    return m


def _piece_finish(base, name, seed, roughness, tint=1.0):
    """A deterministic piece finish: modest tint, independent sheen and subtle edge polish."""
    existing = bpy.data.materials.get(name)
    if existing is not None:
        return existing
    rng = random.Random(seed)
    m = base.copy()
    m.name = name
    m["weathered"] = True
    nodes, links = m.node_tree.nodes, m.node_tree.links
    bs = nodes["Principled BSDF"]
    rgb = tuple(tint * rng.uniform(0.95, 1.04) for _ in range(3))
    if bs.inputs["Base Color"].is_linked:
        original = bs.inputs["Base Color"].links[0].from_socket
    else:
        color = nodes.new("ShaderNodeRGB")
        color.outputs[0].default_value = bs.inputs["Base Color"].default_value
        original = color.outputs[0]
    mix = nodes.new("ShaderNodeMixRGB")
    mix.blend_type = "MULTIPLY"
    mix.inputs[0].default_value = 1.0
    mix.inputs[2].default_value = (*rgb, 1.0)
    links.new(original, mix.inputs[1])
    links.new(mix.outputs[0], bs.inputs["Base Color"])
    noise = nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 95.0
    noise.inputs["Detail"].default_value = 2.0
    geometry = nodes.new("ShaderNodeNewGeometry")
    edge = nodes.new("ShaderNodeValToRGB")
    edge.color_ramp.elements[0].position = 0.48
    edge.color_ramp.elements[1].position = 0.57
    links.new(geometry.outputs["Pointiness"], edge.inputs[0])
    wear = nodes.new("ShaderNodeMath")
    wear.operation = "MULTIPLY"
    links.new(edge.outputs["Color"], wear.inputs[0])
    links.new(noise.outputs["Fac"], wear.inputs[1])
    polish = nodes.new("ShaderNodeMapRange")
    polish.inputs["To Min"].default_value = roughness
    polish.inputs["To Max"].default_value = max(0.1, roughness - 0.065)
    links.new(wear.outputs[0], polish.inputs["Value"])
    links.new(polish.outputs["Result"], bs.inputs["Roughness"])
    bs.inputs["Emission Strength"].default_value = 0.0
    m["ir_piece_roughness"] = roughness
    m["ir_piece_tint"] = list(rgb)
    return m


def _light(name, kind, loc, energy, rgb=(1.0, 0.92, 0.82), **kw):
    ld = bpy.data.lights.new(name, kind); ld.energy = energy * LIGHT; ld.color = rgb
    if kind == "AREA":
        ld.shape = "RECTANGLE"; ld.size = kw.get("sx", 1.0); ld.size_y = kw.get("sy", 1.0)
    elif kind == "SPOT":
        ld.spot_size = math.radians(kw.get("angle", 80)); ld.spot_blend = 0.6; ld.shadow_soft_size = 0.05
    else:
        ld.shadow_soft_size = kw.get("r", 0.1)
    o = bpy.data.objects.new(name, ld); o.location = loc; bpy.context.scene.collection.objects.link(o)
    return o


def _spec():
    if "spec" not in _S:
        _S["spec"] = json.load(open(SPEC))
    return _S["spec"]


def _fx(cat):
    return [f for f in _spec()["fixtures"] if f["category"] == cat]


def _zc():
    return _S["zc"]


# ---- books -----------------------------------------------------------------------------------------------------------------------------------------------------
class Books:
    """Textured covers/spines from every shared atlas, with nonrepeating fixture decks."""
    def __init__(self, tag, rng, n_atlas=None):
        from room_planner import proc_bookstore as pb
        self.tag, self.rng = tag, rng
        n_atlas = pb.meta()["n_atlases"] if n_atlas is None else n_atlas
        if not 1 <= n_atlas <= pb.meta()["n_atlases"]:
            raise ValueError("book atlas count outside shared metadata")
        # Separate cover RNG leaves the placement RNG free to keep irregular books.
        self.cover_rng = random.Random(repr(rng.getstate()) + tag)
        self.cover_deck, self.last_cover, self.cover_counts = [], None, {}
        self.bms = [bmesh.new() for _ in range(n_atlas)]
        for bm in self.bms:
            bm.loops.layers.uv.verify()
        self.n = 0
        self.metrics = {"flat": 0, "leaning": 0, "height_min": 99.0, "height_max": 0.0}

    def add(self, c, dims, mode="face_out", yaw=0.0, tilt=0.0, lean=0.0):
        from room_planner import proc_bookstore as pb
        if not self.cover_deck:
            self.cover_deck = [(k, idx) for k in range(len(self.bms))
                               for idx in range(pb.meta()["n_covers"])]
            self.cover_rng.shuffle(self.cover_deck)
            if len(self.cover_deck) > 1 and self.cover_deck[-1] == self.last_cover:
                self.cover_deck[0], self.cover_deck[-1] = self.cover_deck[-1], self.cover_deck[0]
        k, cover_idx = self.cover_deck.pop()
        self.last_cover = (k, cover_idx)
        self.cover_counts[k] = self.cover_counts.get(k, 0) + 1
        bm = self.bms[k]; uvl = bm.loops.layers.uv.verify()
        vs = pb.add_book(bm, uvl, (0, 0, 0), dims, mode, cover_idx, lean=lean)
        # Preserve cover AND the matching varied printed spine; only page edges
        # use paper. Formerly 82% of all printed faces became eight flat colours.
        for f in {f for v in vs for f in v.link_faces}:
            normal = tuple(round(v) for v in f.normal)
            f.material_index = 0 if normal in pb.ROLES[mode] else 1
        if tilt:                                               # lean back about the book's local Y axis (cover faces +X): top moves toward -X
            bmesh.ops.rotate(bm, cent=(0, 0, -dims[2] / 2), matrix=Matrix.Rotation(tilt, 3, "Y"), verts=vs)
        if yaw:
            bmesh.ops.rotate(bm, cent=(0, 0, 0), matrix=Matrix.Rotation(yaw, 3, "Z"), verts=vs)
        bmesh.ops.translate(bm, vec=tuple(c), verts=vs)
        self.n += 1
        self.metrics["flat"] += mode == "flat"
        self.metrics["leaning"] += abs(lean) > 0.025 or abs(tilt) > 0.10
        if mode != "flat":
            self.metrics["height_min"] = min(self.metrics["height_min"], dims[2])
            self.metrics["height_max"] = max(self.metrics["height_max"], dims[2])

    def flush(self):
        from room_planner import proc_bookstore as pb
        _S.setdefault("book_metrics", {})[self.tag] = dict(self.metrics, total=self.n, atlas_counts=dict(self.cover_counts),
                                                       cover_pool=len(self.bms) * pb.meta()["n_covers"])
        out = []
        for k, bm in enumerate(self.bms):
            if not bm.faces:
                bm.free(); continue
            me = bpy.data.meshes.new(f"{self.tag}_{k}"); bm.to_mesh(me); bm.free(); me.materials.append(pb.atlas_material(k))
            me.materials.append(_flat("ir_bh_paper_edges", (0.80, 0.77, 0.68), 0.75))
            o = bpy.data.objects.new(f"{self.tag}_{k}", me); bpy.context.scene.collection.objects.link(o); out.append(o)
        return out


def _real():
    import real_assets as ra
    return ra


# ---- parts -----------------------------------------------------------------------------------------------------------------------------------------------------
def _clean(stats):
    names = ("VeneerCeilingFactory", "LedPanelsFactory", "HangingBarsFactory", "TrackLoopFactory", "DirectionBoardFactory", "AboCeilingFixtureFactory", "BookIslandTableFactory", "BookWallShelfFactory",
             "PopStandFactory", "SectionSignFactory", "DisplayTableFactory", "ClothingRackFactory", "WallPosterFactory", "OliveTreeFactory", "CafeCounterFactory", "RegisterFactory",
             "AcCassetteFactory", "BestsellerTableFactory", "BestsellerSignFactory", "CeilingGridFactory", "DropCeilingFactory", "CeilingLightFactory")
    k = 0
    for o in list(bpy.data.objects):
        if o.name.startswith(names):
            bpy.data.objects.remove(o, do_unlink=True); k += 1
    for o in list(bpy.data.objects):                                    # the generic fill's lights go with the pieces (point / spot / area lamps of those pass families)
        if o.type == "LIGHT" and o.name.startswith(("PointLampFactory", "LedPanel", "ir_track")):
            bpy.data.objects.remove(o, do_unlink=True); k += 1
    c = bpy.data.objects.get(f"{ROOM}.ceiling")
    _S["zc"] = max((c.matrix_world @ Vector(v)).z for v in c.bound_box) if c is not None else 7.56
    stats["bh_clean_removed"] = k


def _floor(stats):
    f = bpy.data.objects.get(f"{ROOM}.floor")
    if f is None:
        return
    m = bpy.data.materials.get("ir_bh_parquet_real")
    if m is None:
        m = _flat("ir_bh_parquet_real", (0.36, 0.31, 0.245), 0.47)
        nt = m.node_tree; N, L = nt.nodes, nt.links; b = N["Principled BSDF"]
        tc = N.new("ShaderNodeTexCoord"); mp = N.new("ShaderNodeMapping"); L.new(tc.outputs["Object"], mp.inputs["Vector"])
        rot = N.new("ShaderNodeMapping"); rot.inputs["Rotation"].default_value = (0, 0, math.pi / 2); L.new(mp.outputs["Vector"], rot.inputs["Vector"])
        def brick(vec):
            br = N.new("ShaderNodeTexBrick"); br.offset = 0.0; br.squash = 1.0
            br.inputs["Scale"].default_value = 1.0; br.inputs["Brick Width"].default_value = 0.5; br.inputs["Row Height"].default_value = 0.1; br.inputs["Mortar Size"].default_value = 0.0015
            br.inputs["Color1"].default_value = (0.47, 0.295, 0.15, 1); br.inputs["Color2"].default_value = (0.43, 0.27, 0.137, 1); br.inputs["Mortar"].default_value = (0.10, 0.09, 0.075, 1); br.inputs["Bias"].default_value = 0.0
            L.new(vec, br.inputs["Vector"]); return br
        b1, b2 = brick(mp.outputs["Vector"]), brick(rot.outputs["Vector"])
        ck = N.new("ShaderNodeTexChecker"); ck.inputs["Scale"].default_value = 2.0; ck.inputs["Color1"].default_value = (1, 1, 1, 1); ck.inputs["Color2"].default_value = (0, 0, 0, 1); L.new(mp.outputs["Vector"], ck.inputs["Vector"])
        col = N.new("ShaderNodeMix"); col.data_type = "RGBA"; L.new(ck.outputs["Fac"], col.inputs["Factor"]); L.new(b1.outputs["Color"], col.inputs["A"]); L.new(b2.outputs["Color"], col.inputs["B"])
        grain_outputs = []
        for vec in (mp.outputs["Vector"], rot.outputs["Vector"]):
            stretch = N.new("ShaderNodeVectorMath")
            stretch.operation = "MULTIPLY"
            stretch.inputs[1].default_value = (1.0, 45.0, 2.0)
            noise = N.new("ShaderNodeTexNoise")
            noise.inputs["Scale"].default_value = 3.0
            noise.inputs["Detail"].default_value = 3.0
            L.new(vec, stretch.inputs[0])
            L.new(stretch.outputs["Vector"], noise.inputs["Vector"])
            grain_outputs.append(noise.outputs["Fac"])
        gm = N.new("ShaderNodeMixRGB")
        L.new(ck.outputs["Fac"], gm.inputs[0])
        L.new(grain_outputs[0], gm.inputs[1])
        L.new(grain_outputs[1], gm.inputs[2])
        tint = N.new("ShaderNodeMixRGB")
        tint.blend_type = "MULTIPLY"
        tint.inputs[0].default_value = 0.16
        L.new(col.outputs["Result"], tint.inputs[1])
        L.new(gm.outputs[0], tint.inputs[2])
        L.new(tint.outputs[0], b.inputs["Base Color"])
        fac = N.new("ShaderNodeMix"); fac.data_type = "FLOAT"; L.new(ck.outputs["Fac"], fac.inputs["Factor"]); L.new(b1.outputs["Fac"], fac.inputs[2]); L.new(b2.outputs["Fac"], fac.inputs[3])
        bu = N.new("ShaderNodeBump"); bu.inputs["Strength"].default_value = 0.2; bu.inputs["Distance"].default_value = 0.0004
        L.new(fac.outputs["Result"], bu.inputs["Height"]); L.new(bu.outputs["Normal"], b.inputs["Normal"])
        def board_random(vector, tag):
            divide = N.new("ShaderNodeVectorMath")
            divide.operation = "DIVIDE"
            divide.inputs[1].default_value = (0.5, 0.1, 1.0)
            cell = N.new("ShaderNodeVectorMath")
            cell.operation = "FLOOR"
            noise = N.new("ShaderNodeTexWhiteNoise")
            noise.name = "Per plank roughness " + tag
            noise.noise_dimensions = "3D"
            L.new(vector, divide.inputs[0])
            L.new(divide.outputs["Vector"], cell.inputs[0])
            L.new(cell.outputs["Vector"], noise.inputs["Vector"])
            return noise.outputs["Value"]
        r1 = board_random(mp.outputs["Vector"], "longitudinal")
        r2 = board_random(rot.outputs["Vector"], "transverse")
        rough = N.new("ShaderNodeMixRGB")
        L.new(ck.outputs["Fac"], rough.inputs[0])
        L.new(r1, rough.inputs[1])
        L.new(r2, rough.inputs[2])
        remap = N.new("ShaderNodeMapRange")
        remap.name = "Floor board sheen 0.34 to 0.60"
        remap.inputs["To Min"].default_value = 0.32
        remap.inputs["To Max"].default_value = 0.48
        L.new(rough.outputs[0], remap.inputs["Value"])
        L.new(remap.outputs["Result"], b.inputs["Roughness"])
        m["ir_roughness_range"] = [0.32, 0.48]
    for sl in f.material_slots:
        sl.material = m
    stats["bh_floor"] = {"parquet": 1, "per_board_roughness": [0.32, 0.48], "palette": "honey oak with retained per-board variation"}


def _ceiling_cell_liners(xs, ys, zc, depth, thickness, material):
    """Dark recess interiors behind the original oak edges; all timber geometry/materials remain intact."""
    verts, faces = [], []
    for i in range(len(xs) - 1):
        for j in range(len(ys) - 1):
            x0, x1 = xs[i] + thickness / 2 + 0.001, xs[i + 1] - thickness / 2 - 0.001
            y0, y1 = ys[j] + thickness / 2 + 0.001, ys[j + 1] - thickness / 2 - 0.001
            lo, hi = zc - depth + 0.025, zc + 0.10
            n = len(verts)
            verts.extend([(x0, y0, lo), (x1, y0, lo), (x1, y1, lo), (x0, y1, lo),
                          (x0, y0, hi), (x1, y0, hi), (x1, y1, hi), (x0, y1, hi)])
            faces.extend([(n, n + 1, n + 5, n + 4), (n + 1, n + 2, n + 6, n + 5),
                          (n + 2, n + 3, n + 7, n + 6), (n + 3, n, n + 4, n + 7)])
    me = bpy.data.meshes.new("BHCeilingCellLiners")
    me.from_pydata(verts, [], faces)
    me.materials.append(material)
    obj = bpy.data.objects.new("BHCeilingCellLiners", me)
    bpy.context.scene.collection.objects.link(obj)
    return (len(xs) - 1) * (len(ys) - 1)


def _ceiling(stats):
    zc = _zc(); fl = _fl(); wood = _oak("ir_bh_lattice", (0.5, 0.31, 0.16)); dark = _flat("ir_bh_ceildark", (0.03, 0.025, 0.02), 0.9)
    c = bpy.data.objects.get(f"{ROOM}.ceiling")
    recess = dark
    if c is not None:
        recess = bpy.data.materials.new("ir_bh_recess_neutral")
        recess.use_nodes = True
        recess["weathered"] = True
        bs = recess.node_tree.nodes["Principled BSDF"]
        bs.inputs["Base Color"].default_value = (0.008, 0.008, 0.008, 1)
        bs.inputs["Roughness"].default_value = 0.95
        bs.inputs["Emission Strength"].default_value = 0.0
        c.data = c.data.copy()
        c.data.materials.clear()
        c.data.materials.append(recess)
        c.location.z += 0.10
        removed = 0
        for name in (f"{ROOM}.meshed", f"{ROOM}.exterior"):
            obj = bpy.data.objects.get(name)
            if obj is None:
                continue
            obj.data = obj.data.copy()
            bm = bmesh.new()
            bm.from_mesh(obj.data)
            faces = [face for face in bm.faces if abs(face.normal.z) > 0.5 and
                     all((obj.matrix_world @ v.co).z >= zc - 0.025 for v in face.verts)]
            removed += len(faces)
            bmesh.ops.delete(bm, geom=faces, context='FACES')
            bm.to_mesh(obj.data)
            bm.free()
        stats["bh_recess_cleanup"] = {"duplicate_faces_removed": removed, "offset_m": 0.10, "roughness": 0.95}
    cell, dep, th = 0.45, 0.3, 0.035
    xs = [0.12 + cell * i for i in range(int((W - 0.24) / cell) + 1)]; ys = [0.12 + cell * j for j in range(int((D - 0.24) / cell) + 1)]
    prims = [("box", x, D / 2, zc - dep / 2, th, D - 0.24, dep) for x in xs] + [("box", W / 2, y, zc - dep / 2, W - 0.24, th, dep) for y in ys]
    main = [("box", x, D / 2, zc - 0.22, 0.16, D - 0.24, 0.44) for x in [4.5 * i for i in range(1, 9)]] + [("box", W / 2, y, zc - 0.22, W - 0.24, 0.16, 0.44) for y in [4.3 * j for j in range(1, 6)]]
    rng = random.Random(807)
    variants = [_piece_finish(wood, f"ir_bh_lattice_piece_{k}", 190 + k, 0.38 + 0.02 * k, 0.96 + 0.025 * k) for k in range(6)]
    groups = [(mat, []) for mat in variants]
    for member in prims + main:
        groups[rng.randrange(len(groups))][1].append(member)
    _furniture_bevel(fl.mesh_object("BHLattice", groups, bevel=False), 0.002)
    stats["bh_ceiling_finish_variants"] = len(variants)
    stats["bh_dark_recess_cells"] = _ceiling_cell_liners(xs, ys, zc, dep, th, recess)
    dl = _emit("ir_bh_dl", (1.0, 0.84, 0.62), 40.0)
    discs = []
    for i in range(1, 14):
        for j in range(1, 9):
            x, y = 3.0 * i, 3.2 * j
            if x < W - 0.5 and y < D - 0.5:
                discs.append(("cyl", (x, y, zc - 0.06), (x, y, zc - 0.07), 0.07, 14))
    fl.mesh_object("BHDownlights", [(dl, discs)], bevel=False)
    stats["bh_ceiling"] = {"beams": len(prims) + len(main), "downlights": len(discs)}


def _columns(stats):
    fl = _fl(); zc = _zc(); wh = _flat("ir_bh_plaster", (0.9, 0.9, 0.88), 0.6)
    wl = bpy.data.objects.get(f"{ROOM}.wall")                          # r2: walls and columns shared the peach wood tone: neutral white plaster against the warm oak
    if wl is not None:
        for sl in wl.material_slots:
            sl.material = wh
    prims = []
    for f in _fx("round_column"):
        x, y = f["position_m"][:2]
        prims += [("cyl", (x, y, 0.1), (x, y, zc), 0.35, 36), ("cyl", (x, y, 0.1), (x, y, 0.3), 0.41, 36), ("cyl", (x, y, zc - 0.25), (x, y, zc), 0.41, 36)]
    fl.mesh_object("BHColumns", [(wh, prims)], bevel=False)
    stats["bh_columns"] = len(prims) // 3


def _mezz(stats):
    fl = _fl(); cream = _flat("ir_bh_mezz", (0.9, 0.88, 0.82), 0.6); br = _flat("ir_bh_brass", (0.72, 0.52, 0.22), 0.3, 1.0); steel = _flat("ir_bh_steel", (0.025, 0.025, 0.03), 0.4, 1.0)
    gl = _flat("ir_bh_rail_glass", (0.78, 0.9, 0.95), 0.02, transmission=0.9); dl = _emit("ir_bh_dl", (1.0, 0.84, 0.62), 40.0); oak = _oak()
    xe, z0, z1 = 5.0, 4.0, 4.2; yl = 24.6                                        # slab x 0-5, a landing x 5-6.5 / y 24.6-25.9 joins the stair
    slab = [("box", xe / 2 + 0.06, D / 2, (z0 + z1) / 2, xe - 0.12, D - 0.24, z1 - z0), ("box", 5.75, (yl + D - 0.1) / 2, (z0 + z1) / 2, 1.5, D - 0.1 - yl, z1 - z0)]
    fascia = [("box", xe, D / 2, z0 - 0.1, 0.1, D - 0.24, 0.35)]
    ys = [0.4 + 1.6 * i for i in range(int((yl - 0.4) / 1.6) + 1)]                  # r2: the rail was invisible (1.5 m panes, 5 cm posts): black steel posts every 1 m, glass between, a thick brass cap rail and a base channel
    posts = [("box", xe - 0.05, y, z1 + 0.55, 0.025, 0.025, 1.1) for y in ys] + [("box", xe - 0.05, (ys[0] + ys[-1]) / 2, z1 + 0.04, 0.035, ys[-1] - ys[0], 0.035)]
    cap = [("box", xe - 0.05, (ys[0] + ys[-1]) / 2, z1 + 1.12, 0.035, ys[-1] - ys[0] + 0.06, 0.025)]
    pane = [("box", xe - 0.05, (ys[k] + ys[k + 1]) / 2, z1 + 0.6, 0.015, ys[k + 1] - ys[k] - 0.03, 1.0) for k in range(len(ys) - 1)]
    discs = [("cyl", (x, y, z0 - 0.01), (x, y, z0 - 0.02), 0.07, 14) for x in (1.5, 3.5) for y in [2 + 3 * i for i in range(8)]]
    fz = _furniture_floor()
    n = 20; run = (yl - 19.0) / n; rise = (z1 - fz) / n; steps = []; sp = []; sg = []
    for k in range(n):                                                                 # straight flight along +y at x 5.3-6.5 up to the landing
        yk = 19.0 + (k + 0.5) * run; zt = fz + rise * (k + 1)
        steps.append(("box", 5.9, yk, (zt + fz) / 2, 1.2, run, zt - fz))
        steps.append(("box", 5.9, yk - run / 2 + 0.012, zt, 1.22, 0.045, 0.025)) 
    for sx_ in (5.3, 6.5):
        for k in range(0, n, 3):
            sp.append(("box", sx_, 19.0 + (k + 0.5) * run, fz + rise * (k + 1) + 0.48, 0.04, 0.04, 0.96))
        cap.append(("cyl", (sx_, 19.0, fz + 1.0), (sx_, yl, z1 + 1.0), 0.028, 16))
    _furniture_bevel(fl.mesh_object("BHMezzanine", [(cream, slab + fascia), (br, cap), (steel, posts + sp),
                                                  (gl, pane), (dl, discs), (oak, steps)], bevel=False), 0.003)
    for i in range(4):
        _light(f"ir_bh_mezz_{i}", "AREA", (2.5, 3.5 + 6.2 * i, z0 - 0.1), 46, sx=2.0, sy=2.0)
    stats["bh_mezz"] = {"posts": len(ys), "stair_steps": n}


def _tower(i, f, rng, oak, black, led):
    fl = _fl(); x, y = f["position_m"][:2]; sx, sy, h = f["size_m"]
    prims, strips = [], []
    ncol, nlev = 5, 13; lh = (h - 0.2) / nlev; cw = (sx - 0.1) / ncol
    prims += [("box", x - sx / 2, y, h / 2, 0.05, sy, h), ("box", x + sx / 2, y, h / 2, 0.05, sy, h), ("box", x, y, h / 2, sx, 0.04, h), ("box", x, y, h + 0.02, sx, sy, 0.06), ("box", x, y, 0.07, sx, sy, 0.14)]
    bm = Books(f"BHTower{i}", rng)
    for face in (-1, 1):
        yf = y + face * sy / 2; yd = y + face * (sy / 4 + 0.02)                                # cubby front plane at the face, depth sy/2 - 0.02
        for lv in range(nlev + 1):
            z = 0.15 + lv * lh
            prims.append(("box", x, yd, z, sx - 0.04, sy / 2 - 0.02, 0.035))
            if lv < nlev:
                strips.append(("box", x, yf - face * 0.03, z - 0.03, sx - 0.12, 0.012, 0.012))
        for c in range(ncol + 1):
            prims.append(("box", x - sx / 2 + 0.05 + c * cw, yd, h / 2, 0.03, sy / 2 - 0.02, h - 0.1))
        yaw = -math.pi / 2 if face < 0 else math.pi / 2
        for lv in range(nlev):
            if lv > 8 and rng.random() > 0.35:
                continue
            z = 0.15 + lv * lh + 0.0175
            for c in range(ncol):
                cx0 = x - sx / 2 + 0.05 + c * cw
                n = rng.choice((2, 3, 3)) if lv <= 8 else 2
                pitch = (cw - 0.08) / n
                for b in range(n):
                    bx = cx0 + 0.04 + (b + 0.5) * pitch + rng.uniform(-0.012, 0.012)
                    depth = rng.uniform(0.11, 0.18)
                    if (lv + c * 3 + b + i) % 19 == 0:
                        for stack in range(rng.randint(2, 3)):
                            thick = 0.032
                            bm.add((bx, yf - face * 0.19, z + thick * (stack + 0.5)),
                                   (0.19, min(pitch - 0.03, 0.22), thick), "flat", yaw=rng.uniform(-0.10, 0.10))
                    elif (lv * 7 + c + b + i) % 29 != 0:
                        bw = rng.uniform(0.145, min(0.225, pitch - 0.03))
                        bh = min(lh - 0.055, rng.uniform(0.22, 0.38))
                        bm.add((bx, yf - face * depth, z + bh / 2), (rng.uniform(0.024, 0.045), bw, bh),
                               "face_out", yaw=yaw, tilt=rng.uniform(0.02, 0.15), lean=rng.uniform(-0.055, 0.055))
    dark = _flat("ir_bh_reveal", (0.05, 0.03, 0.02), 0.6); head = _flat("ir_bh_header", (0.14, 0.12, 0.1), 0.5); rev, hd, edge = [], [], []
    for sgn in (-1, 1):                                                            # r2: the end faces were plain slabs: oak panelling with reveals, a blank header board, LED edge strips
        xe = x + sgn * (sx / 2 + 0.03)
        for k in range(1, 6):
            rev.append(("box", xe, y, h * k / 6, 0.012, sy - 0.1, 0.014))
        for k in (-1, 0, 1):
            rev.append(("box", xe, y + k * sy / 3.2, h / 2, 0.012, 0.014, h - 0.3))
        hd.append(("box", xe + sgn * 0.01, y, h - 0.55, 0.03, sy * 0.75, 0.45))
        for yy in (y - sy / 2 + 0.03, y + sy / 2 - 0.03):
            edge.append(("box", xe + sgn * 0.008, yy, h / 2, 0.012, 0.014, h - 0.4))
    wal = _flat("ir_bh_walnut", (0.2, 0.1, 0.05), 0.4); brass = _flat("ir_bh_brass", (0.8, 0.62, 0.25), 0.3, 1.0); fr, br = [], []
    for sgn in (-1, 1):                                                            # r4: the end faces still read as plain cork slabs: dark walnut raised-panel frames (stiles + rails) with brass inlay lines, 3 panels over the height
        xe = x + sgn * (sx / 2 + 0.05)
        for k in range(0, 4):
            fr.append(("box", xe, y, 0.35 + k * (h - 0.9) / 3, 0.04, sy - 0.06, 0.12))
        for yy in (y - sy / 2 + 0.07, y + sy / 2 - 0.07, y):
            fr.append(("box", xe, yy, h / 2 - 0.1, 0.04, 0.1, h - 0.9))
        for k in range(3):
            zc = 0.35 + (k + 0.5) * (h - 0.9) / 3
            br += [("box", xe + sgn * 0.015, y, zc - ((h - 0.9) / 3 - 0.2) / 2, 0.012, sy - 0.3, 0.014), ("box", xe + sgn * 0.015, y, zc + ((h - 0.9) / 3 - 0.2) / 2, 0.012, sy - 0.3, 0.014)]
    fl.mesh_object(f"BHTower{i}Frame", [(oak, prims), (led, strips)], bevel=False)
    cheek = _oak("ir_bh_tower_cheek", (0.52, 0.33, 0.16))
    for node in cheek.node_tree.nodes:
        if node.type == 'VECT_MATH' and node.operation == 'MULTIPLY':
            node.inputs[1].default_value = (38.0, 38.0, 1.1)
    for side in (-1, 1):
        _rounded_slab(f"BHTower{i}Cheek{side}", cheek, x + side * (sx / 2 + 0.04), y,
                      (h + 0.05 + _furniture_floor()) / 2, 0.045, sy + 0.02, h + 0.05 - _furniture_floor(),
                      0.015, edge_width=0.003)
    bm.flush()
    for k in range(3):
        _light(f"ir_bh_tower_{i}_{k}", "AREA", (x, y - sy / 2 - 0.25, 1.5 + 2.4 * k), 26, sx=sx * 0.8, sy=0.4)
    return bm.n


def _towers(stats):
    rng = random.Random(41); oak = _oak(); led = _emit("ir_bh_led", (1.0, 0.86, 0.62), 25.0); n = 0
    for i, f in enumerate(_fx("shelving_tower")):
        n += _tower(i, f, rng, oak, None, led)
    stats["bh_towers"] = {"towers": len(_fx("shelving_tower")), "books": n}


def _gondola(i, f, rng, oak, black, led):
    fl = _fl(); x, y = f["position_m"][:2]; L, Dp, H = f["size_m"]
    prims_b = [("box", x - L / 2 + 0.03, y, H / 2, 0.05, Dp, H), ("box", x + L / 2 - 0.03, y, H / 2, 0.05, Dp, H), ("box", x, y, H / 2, L, 0.03, H), ("box", x, y, 0.08, L, Dp - 0.1, 0.16)]
    prims_b = prims_b[2:]
    for sign in (-1, 1):
        _gondola_cheek(f"BHGond{i}Cheek{sign}", black, x + sign * (L / 2 - 0.03), y, _furniture_floor(), Dp, H)
    prims_o, strips, rails = [], [], []
    bm = Books(f"BHGond{i}", rng)
    for side in (-1, 1):
        yf = y + side * (Dp / 2 - 0.02); yaw = -math.pi / 2 if side < 0 else math.pi / 2
        for s in range(4):
            z = 0.3 + s * 0.36
            prims_o.append(("box", x, y + side * (Dp / 4 + 0.01), z, L - 0.1, Dp / 2 - 0.04, 0.03))
            rails.append(("box", x, yf, z + 0.03, L - 0.1, 0.02, 0.07)); strips.append(("box", x, yf - side * 0.03, z - 0.02, L - 0.16, 0.012, 0.012))
            if s > 0:
                angle = math.radians(12)
                _sloped_box(f"BHGond{i}Slope{side}_{s}", oak,
                            (x, yf - side * (0.18 + 0.155 * math.sin(angle)), z + 0.015 + 0.155 * math.cos(angle)),
                            (L - 0.14, 0.025, 0.31), side * angle)
            bx = x - L / 2 + 0.14
            if s == 0:
                while bx < x + L / 2 - 0.14:
                    thick = rng.uniform(0.032, 0.055)
                    bh = rng.uniform(0.21, 0.30)
                    bm.add((bx + thick / 2, yf - side * 0.15, z + 0.015 + bh / 2),
                           (rng.uniform(0.17, 0.22), thick, bh), "spine_out", yaw=yaw, lean=rng.uniform(-0.02, 0.02))
                    bx += thick + rng.uniform(0.012, 0.024)
                continue
            while bx < x + L / 2 - 0.14:
                bw = rng.uniform(0.15, 0.25)
                bh = rng.uniform(0.215, 0.315)
                bm.add((bx, y + side * (Dp / 2 - rng.uniform(0.13, 0.14)), z + 0.015 + bh / 2),
                       (rng.uniform(0.025, 0.046), bw, bh), "face_out", yaw=yaw,
                       tilt=-math.radians(12), lean=rng.uniform(-0.035, 0.035))
                bx += bw + rng.uniform(0.025, 0.065)
        zt = 0.3 + 4 * 0.36                                     # top stack: tidy flat piles
        for k in range(5):
            if side > 0:
                for stack in range(rng.randint(2, 4)):
                    bm.add((x - L / 2 + 0.4 + k * (L - 0.8) / 4 + rng.uniform(-0.02, 0.02), y,
                            H + 0.0175 + 0.035 * stack), (rng.uniform(0.18, 0.23), rng.uniform(0.24, 0.29), 0.035),
                           "flat", yaw=rng.uniform(-0.12, 0.12))
    fl.mesh_object(f"BHGond{i}Frame", [(black, prims_b), (oak, prims_o + rails), (led, strips)], bevel=False)
    bm.flush()
    _light(f"ir_bh_gond_{i}", "AREA", (x, y, 1.8), 24 + 5 * (i % 3), sx=L * 0.7, sy=0.8)
    return bm.n


def _gondolas(stats):
    rng = random.Random(7); oak = _oak(); black = _flat("ir_bh_steel", (0.025, 0.025, 0.03), 0.4, 1.0); led = _emit("ir_bh_led", (1.0, 0.86, 0.62), 25.0); n = 0
    grid = []                                                                    # r2: the plan's 3 x 4 grid (spec lists 3 rows): rows at y 5.5 / 10 / 14.5 / 19, columns at the spec x
    for xc in sorted({f["position_m"][0] for f in _fx("book_gondola")}):
        for yr in (9.0, 14.0, 19.0):
            g = dict(_fx("book_gondola")[0]); g["position_m"] = [xc, yr, 0]; grid.append(g)
    for i, f in enumerate(grid):
        n += _gondola(i, f, rng, oak, black, led)
    stats["bh_gondolas"] = {"gondolas": len(grid), "books": n}


def _dome(name, x, y, z, r, mat):
    bm = bmesh.new(); bmesh.ops.create_uvsphere(bm, u_segments=24, v_segments=12, radius=r)
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if v.co.z < -0.001], context="VERTS")
    bmesh.ops.translate(bm, vec=(x, y, z), verts=bm.verts)
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free(); me.materials.append(mat)
    for p in me.polygons:
        p.use_smooth = True
    o = bpy.data.objects.new(name, me); bpy.context.scene.collection.objects.link(o)
    return o


def _furniture_floor():
    floor = bpy.data.objects.get(f"{ROOM}.floor")
    return max((floor.matrix_world @ Vector(c)).z for c in floor.bound_box) + 0.002 if floor else 0.002


def _furniture_bevel(o, width=0.0045):
    """Bake real edge geometry so the detail survives mesh export."""
    bm = bmesh.new()
    bm.from_mesh(o.data)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    bm.to_mesh(o.data)
    bm.free()
    bpy.context.view_layer.objects.active = o
    mod = o.modifiers.new("Furniture edge radius", "BEVEL")
    mod.width = width
    mod.segments = 3
    mod.limit_method = "ANGLE"
    bpy.ops.object.modifier_apply(modifier=mod.name)
    o["ir_edge_radius_m"] = width
    return o


def _rounded_slab(name, mat, x, y, z, sx, sy, h, radius=0.06, edge_width=0.0045):
    """Rounded plan corners plus a separate 3 mm eased top/bottom edge."""
    r = min(radius, sx / 2 - 0.001, sy / 2 - 0.001)
    ring = []
    for cx, cy, start in ((sx / 2 - r, sy / 2 - r, 0), (-sx / 2 + r, sy / 2 - r, 90),
                          (-sx / 2 + r, -sy / 2 + r, 180), (sx / 2 - r, -sy / 2 + r, 270)):
        for j in range(9):
            a = math.radians(start + 90 * j / 8)
            ring.append((x + cx + r * math.cos(a), y + cy + r * math.sin(a)))
    n = len(ring)
    verts = [(px, py, z + side * h / 2) for side in (-1, 1) for px, py in ring]
    faces = [tuple(reversed(range(n))), tuple(range(n, 2 * n))]
    faces += [(j, (j + 1) % n, (j + 1) % n + n, j + n) for j in range(n)]
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts, [], faces)
    me.materials.append(mat)
    o = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(o)
    return _furniture_bevel(o, edge_width)


def _taper_leg(name, mat, bottom, top, r_bottom=0.018, r_top=0.03):
    bm = bmesh.new()
    v = Vector(top) - Vector(bottom)
    part = bmesh.ops.create_cone(bm, cap_ends=True, segments=20, radius1=r_bottom, radius2=r_top, depth=v.length, calc_uvs=True)
    bmesh.ops.rotate(bm, cent=(0, 0, 0), matrix=Vector((0, 0, 1)).rotation_difference(v.normalized()).to_matrix(), verts=part["verts"])
    bmesh.ops.translate(bm, vec=(Vector(bottom) + Vector(top)) / 2, verts=part["verts"])
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    me.materials.append(mat)
    for face in me.polygons:
        face.use_smooth = len(face.vertices) == 4
    o = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(o)
    return _furniture_bevel(o)


def _leather():
    m = _flat("ir_bh_cognac_leather", (0.28, 0.135, 0.065), 0.48)
    bs = m.node_tree.nodes["Principled BSDF"]
    bs.inputs["Emission Strength"].default_value = 0.0
    if "Coat Weight" in bs.inputs:
        bs.inputs["Coat Weight"].default_value = 0.12
        bs.inputs["Coat Roughness"].default_value = 0.4
    noise = m.node_tree.nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 210.0
    bump = m.node_tree.nodes.new("ShaderNodeBump")
    bump.inputs["Strength"].default_value = 0.12
    bump.inputs["Distance"].default_value = 0.0006
    m.node_tree.links.new(noise.outputs["Fac"], bump.inputs["Height"])
    m.node_tree.links.new(bump.outputs["Normal"], bs.inputs["Normal"])
    return m


def _cafe_chair(name, x, y, yaw, oak, leather, fz):
    """Solid oak splayed frame, pillowed seat and upholstered curved barrel back; local front -Y."""
    before = set(bpy.data.objects)
    for sx in (-1, 1):
        for sy in (-1, 1):
            _taper_leg(name + f"Leg{sx}{sy}", oak, (sx * 0.225, sy * 0.215, fz + 0.003),
                       (sx * 0.177, sy * 0.157, fz + 0.43), 0.019, 0.028)
    _rounded_slab(name + "SeatRail", oak, 0, 0, fz + 0.412, 0.47, 0.43, 0.045, 0.13)
    seat = _real().soft(name + "LeatherSeat", leather, 0, -0.005, fz + 0.465, 0.49, 0.46, 0.09, seed=81, lump=0.001)
    bpy.context.view_layer.objects.active = seat
    bpy.ops.object.modifier_apply(modifier=seat.modifiers[0].name)
    # The back is a thick curved surface, rather than a flat rectangular panel.
    n = 32
    verts = []
    for z, rx, ry in ((fz + 0.51, 0.255, 0.22), (fz + 0.81, 0.275, 0.245)):
        for offset in (-0.018, 0.018):
            for j in range(n + 1):
                a = math.radians(22 + 136 * j / n)
                verts.append(((rx + offset) * math.cos(a), (ry + offset) * math.sin(a), z + 0.012 * math.sin(a)))
    w = n + 1
    faces = []
    for j in range(n):
        faces += [(j, j + 1, 2 * w + j + 1, 2 * w + j),
                  (w + j + 1, w + j, 3 * w + j, 3 * w + j + 1),
                  (j + 1, j, w + j, w + j + 1),
                  (2 * w + j, 2 * w + j + 1, 3 * w + j + 1, 3 * w + j)]
    faces += [(0, 2 * w, 3 * w, w), (n, w + n, 3 * w + n, 2 * w + n)]
    me = bpy.data.meshes.new(name + "CurvedBack")
    me.from_pydata(verts, [], faces)
    me.materials.append(leather)
    back = bpy.data.objects.new(name + "CurvedBack", me)
    bpy.context.scene.collection.objects.link(back)
    for face in me.polygons:
        face.use_smooth = True
    _furniture_bevel(back)
    for sx in (-1, 1):
        _taper_leg(name + f"BackSupport{sx}", oak, (sx * 0.18, 0.15, fz + 0.41),
                   (sx * 0.22, 0.16, fz + 0.75), 0.018, 0.016)
    for obj in set(bpy.data.objects) - before:
        obj.location = (x, y, 0)
        obj.rotation_euler.z = yaw
        obj["ir_furniture_design"] = "oak_cognac_barrel_chair"


def _cafe_table(name, x, y, oak, fz, radius=0.43):
    top = _fl().mesh_object(name + "OakTop", [(oak, [("cyl", (x, y, fz + 0.711), (x, y, fz + 0.75), radius, 96)])], bevel=False)
    for face in top.data.polygons:
        face.use_smooth = len(face.vertices) == 4
    _furniture_bevel(top)
    for q in range(4):
        a = math.pi / 4 + q * math.pi / 2
        _taper_leg(name + f"Leg{q}", oak,
                   (x + 0.29 * math.cos(a), y + 0.29 * math.sin(a), fz + 0.003),
                   (x + 0.20 * math.cos(a), y + 0.20 * math.sin(a), fz + 0.715), 0.022, 0.038)
    apron = _fl().mesh_object(name + "Apron", [(oak, [("cyl", (x, y, fz + 0.66), (x, y, fz + 0.71), 0.255, 64)])], bevel=False)
    _furniture_bevel(apron)
    return fz + 0.75


def _cabinet(name, x, y, L, Dp, top_z, oak, stone):
    """Soft corner casework with a recessed toe-kick, framed inset doors and overhanging stone lip."""
    fz = _furniture_floor()
    seed = 710 if name == "BHCafeCounter" else 720
    oak = _piece_finish(oak, name + "Finish", seed, 0.36 if seed == 710 else 0.40)
    stone = _piece_finish(stone, name + "StoneFinish", seed + 1, 0.21 if seed == 710 else 0.24)
    plinth = _oak("ir_bh_furn_plinth", (0.16, 0.09, 0.045))
    cream = _flat("ir_bh_furn_inset", (0.72, 0.67, 0.55), 0.52)
    _rounded_slab(name + "Plinth", plinth, x, y, fz + 0.06, L - 0.22, Dp - 0.20, 0.12, 0.045)
    bottom, upper = fz + 0.12, top_z - 0.065
    _rounded_slab(name + "OakCase", oak, x, y, (bottom + upper) / 2, L - 0.08, Dp - 0.10, upper - bottom, 0.065)
    _rounded_slab(name + "StoneLip", stone, x, y, top_z - 0.03, L + 0.04, Dp + 0.04, 0.06, 0.09)
    _rounded_slab(name + "OakTopReveal", plinth, x, y, top_z - 0.067, L - 0.025, Dp - 0.025, 0.014, 0.07)
    count = max(2, round(L / 0.72))
    pw = (L - 0.25) / count
    for side in (-1, 1):
        # Panels are inset behind the rail/stile faces, producing actual shadow reveals.
        face_y = y + side * (Dp / 2 - 0.041)
        for i in range(count):
            px = x - (count - 1) * pw / 2 + i * pw
            _rounded_slab(name + f"Inset{side}_{i}", cream, px, face_y, (bottom + upper) / 2,
                          pw - 0.055, 0.012, upper - bottom - 0.15, 0.005)
        rails = [("box", x, face_y + side * 0.012, z, L - 0.23, 0.035, 0.045) for z in (bottom + 0.04, upper - 0.04)]
        rails += [("box", x - count * pw / 2 + i * pw, face_y + side * 0.012, (bottom + upper) / 2,
                   0.035, 0.035, upper - bottom - 0.08) for i in range(count + 1)]
        obj = _fl().mesh_object(name + f"PanelFrame{side}", [(oak, rails)], bevel=False)
        _furniture_bevel(obj)












def _lamps(stats):
    fl = _fl(); br = _flat("ir_bh_brass", (0.72, 0.52, 0.22), 0.3, 1.0); shade = _emit("ir_bh_drum", (1.0, 0.88, 0.7), 1.2)
    for i, f in enumerate(_fx("drum_floor_lamp")):
        x, y = f["position_m"][:2]
        fl.mesh_object(f"BHDrumLamp{i}", [(br, [("cyl", (x, y, 0.02), (x, y, 1.35), 0.012, 8), ("cyl", (x, y, 0.0), (x, y, 0.03), 0.16, 20)]), (shade, [("cyl", (x, y, 1.15), (x, y, 1.65), 0.3, 32)])], bevel=False)
        _light(f"ir_bh_drum_{i}", "POINT", (x, y, 1.4), 90, r=0.2)
    stats["bh_lamps"] = len(_fx("drum_floor_lamp"))


def _leafmat(o):
    """HSSD plant materials render white in the pipeline (plant_fix.py): rebuild each slot as a fresh Principled with the first sRGB image, else leaf green."""
    cache = _S.setdefault("leaf", {})
    for sl in o.material_slots:
        m = sl.material
        if m is None:
            continue
        if m.name not in cache:
            base = None
            if m.use_nodes:
                for nd in m.node_tree.nodes:
                    if nd.type == "TEX_IMAGE" and nd.image is not None and nd.image.size[0] > 0 and nd.image.colorspace_settings.name == "sRGB":
                        base = nd.image; break
            nm = bpy.data.materials.new(f"ir_bh_leaf_{len(cache)}"); nm.use_nodes = True; N, L = nm.node_tree.nodes, nm.node_tree.links; b = N["Principled BSDF"]
            if base is not None:
                t = N.new("ShaderNodeTexImage"); t.image = base; L.new(t.outputs["Color"], b.inputs["Base Color"])
            else:
                b.inputs["Base Color"].default_value = (0.05, 0.22, 0.04, 1.0)
            b.inputs["Roughness"].default_value = 0.5; b.inputs["Metallic"].default_value = 0.0; nm["weathered"] = True
            cache[m.name] = nm
        sl.material = cache[m.name]


def _backdrop(stats):
    """r4: the street card behind the south glazing is the shared Parisian street_photo.png: point the card + ground materials at a tree-lined modern street plate (derived from outside_views/street_day_02, bigglass_cards/street_trees_photo.png) in THIS scene only."""
    img = bpy.data.images.load("/jarvis/project/robomituba/data/venue_refs/bigglass_cards/street_trees_photo.png", check_existing=True); n = 0
    for m in bpy.data.materials:
        if m.name in ("ir_bg_card_street", "ir_bg_groundphoto_street") and m.node_tree:
            for nd in m.node_tree.nodes:
                if nd.type == "TEX_IMAGE":
                    nd.image = img; n += 1
    stats["bh_backdrop"] = n


def _plants(stats):
    ra = _real(); n = 0
    for i, (x, y) in enumerate(((1.2, 1.2), (10.5, 1.2), (1.2, 8.5), (38.5, 1.5), (38.8, 24.5), (6.5, 24.8), (2.0, 24.0), (38.5, 6.0), (38.5, 22.0), (11.0, 5.0))):
        o = ra.hssd(r"plant|ficus|palm|monstera|tree", 70 + i, x, y, 0.0, 0.0, fit=(1.2, 1.2, 2.2), size=(0.9, 4.0))
        # This broad HSSD label matches a green armchair; it overlaps the entrance cafe table.
        if o is not None and "3f9e16dc68b30223b1a417a40395f1823318fb3c" in o.name:
            bpy.data.objects.remove(o, do_unlink=True)
            stats["bh_mislabeled_plant_chair_removed"] = 1
            continue
        n += o is not None
        if o is not None:
            _leafmat(o)
    stats["bh_plants"] = n


def _detail_text(name, body, location, size, material, yaw=0.0):
    data = bpy.data.curves.new(name, "FONT")
    data.body = body
    data.size = size
    data.align_x = "CENTER"
    data.align_y = "CENTER"
    data.extrude = 0.0006
    obj = bpy.data.objects.new(name, data)
    bpy.context.scene.collection.objects.link(obj)
    obj.location = location
    obj.rotation_euler = (math.pi / 2, 0, yaw)
    data.materials.append(material)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    bpy.ops.object.convert(target="MESH")
    obj.select_set(False)
    return obj


def _details(stats):
    """Functional joinery and wayfinding, mounted on measured faces rather than box edges."""
    import wall_face
    lo, hi = wall_face.inner_box(ROOM)
    fz = _furniture_floor()
    oak = _oak("ir_bh_base_oak", (0.29, 0.205, 0.125))
    ivory = _flat("ir_bh_socket_porcelain", (0.77, 0.78, 0.75), 0.31)
    black = _flat("ir_bh_label_ink", (0.025, 0.03, 0.03), 0.56)
    cream = _flat("ir_bh_sign_cream", (0.82, 0.79, 0.67), 0.48)
    trim = []
    openings = []
    for obj in bpy.data.objects:
        if obj.type == "MESH" and obj.name.startswith(("Door", "Window", "BigGlass")):
            points = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
            openings.append(([min(v[k] for v in points) for k in range(3)], [max(v[k] for v in points) for k in range(3)]))
    for side in ("N", "E", "W"):
        horizontal = side == "N"
        axis = 0 if horizontal else 1
        face = wall_face.face(ROOM, side)
        spans = [(lo[axis] + 0.02, hi[axis] - 0.02)]
        cross = 1 - axis
        for a, b in openings:
            if a[cross] - 0.15 <= face <= b[cross] + 0.15:
                split = []
                for start, end in spans:
                    if b[axis] + 0.04 <= start or a[axis] - 0.04 >= end:
                        split.append((start, end))
                    else:
                        if a[axis] - 0.04 > start:
                            split.append((start, a[axis] - 0.04))
                        if b[axis] + 0.04 < end:
                            split.append((b[axis] + 0.04, end))
                spans = split
        for start, end in spans:
            if end - start < 0.1:
                continue
            inward = -1 if side in ("N", "E") else 1
            x, y = ((start + end) / 2, face + inward * 0.013) if horizontal else (face + inward * 0.013, (start + end) / 2)
            trim.append(("box", x, y, fz + 0.044, end - start if horizontal else 0.024,
                         0.024 if horizontal else end - start, 0.085))
    _furniture_bevel(_fl().mesh_object("BHBaseTrim", [(oak, trim)], bevel=False), 0.002)
    sockets = []
    holes = []
    nf = wall_face.face(ROOM, "N")
    ef = wall_face.face(ROOM, "E")
    for x in (7.5, 18.5, 31.8):
        sockets.append(("box", x, nf - 0.009, fz + 0.36, 0.09, 0.016, 0.115))
        for dx in (-0.018, 0.018):
            holes.append(("cyl", (x + dx, nf - 0.019, fz + 0.36), (x + dx, nf - 0.021, fz + 0.36), 0.006, 16))
    for y in (6.2, 12.5, 21.5):
        sockets.append(("box", ef - 0.009, y, fz + 0.36, 0.016, 0.09, 0.115))
        for dy in (-0.018, 0.018):
            holes.append(("cyl", (ef - 0.019, y + dy, fz + 0.36), (ef - 0.021, y + dy, fz + 0.36), 0.006, 16))
    _furniture_bevel(_fl().mesh_object("BHWallSockets", [(ivory, sockets), (black, holes)], bevel=False), 0.002)
    categories = ("FICTION", "ART & DESIGN", "SCIENCE", "TRAVEL", "HISTORY")
    signs = 0
    for i, fixture in enumerate(_fx("shelving_tower")):
        x, y = fixture["position_m"][:2]
        sx, sy, h = fixture["size_m"]
        for side in (-1, 1):
            _detail_text(f"BHTowerCategory{i}_{side}", categories[i % len(categories)],
                         (x + side * (sx / 2 + 0.09), y, h - 0.55), min(0.14, sy / 12), cream, side * math.pi / 2)
            signs += 1
    for i, x in enumerate(sorted({f["position_m"][0] for f in _fx("book_gondola")})):
        for j, y in enumerate((9.0, 14.0, 19.0)):
            fixture = _fx("book_gondola")[0]
            depth = fixture["size_m"][1]
            label_y = y - depth / 2 - 0.023
            _rounded_slab(f"BHShelfLabelPlate{i}_{j}", black, x, label_y, 1.46, 0.72, 0.016, 0.095, 0.006)
            _detail_text(f"BHShelfLabel{i}_{j}", f"{categories[(i + j) % 5]}  {i + 1}.{j + 1}",
                         (x, label_y - 0.010, 1.46), 0.034, cream)
    # The cafe sign is built on its own counter facade; it never covers an opening.
    cafe = _fx("cafe_counter")[0]
    x, y = cafe["position_m"][:2]
    _detail_text("BHCafeServiceSign", "CAFE  /  ORDER HERE", (x, y - cafe["size_m"][1] / 2 - 0.015, 0.80), 0.065, black)
    stats["bh_functional_details"] = {"socket_plates": len(sockets), "base_trim_runs": len(trim), "tower_signs": signs,
                                      "shelf_labels": 9, "cafe_sign": 1, "inner_faces": {"N": nf, "E": ef}}


def _pinned(asset_id, name, x, y, z, yaw=0.0, fit=None):
    cache = _S.setdefault("pinned", {})
    if asset_id not in cache:
        obj = _real().hssd(asset_id, 0, x, y, z, yaw, fit=fit, grow=True)
        if obj is None:
            raise RuntimeError(f"Required B3 asset missing: {asset_id}")
        cache[asset_id] = obj
    else:
        obj = cache[asset_id].copy()
        obj.data = cache[asset_id].data
        bpy.context.scene.collection.objects.link(obj)
        _real()._stand(obj, x, y, z, yaw + math.pi / 2, fit, grow=True)
    obj.name = name
    obj["ir_pinned_asset"] = asset_id
    return obj


def _mushroom(name, x, y, z, radius=0.12):
    brass = _flat("ir_bh_reading_brass", (0.64, 0.43, 0.16), 0.26, 1.0)
    glow = _emit("ir_bh_lamp_diffuser", (1.0, 0.67, 0.34), 2.0)
    _furniture_bevel(_fl().mesh_object(name + "StemBase", [(brass, [
        ("cyl", (x, y, z), (x, y, z + 0.018), radius * 0.5, 32),
        ("cyl", (x, y, z + 0.018), (x, y, z + 0.21), 0.012, 20)]),
        (glow, [("cyl", (x, y, z + 0.205), (x, y, z + 0.21), radius * 0.86, 32)])], bevel=False), 0.002)
    _dome(name + "Shade", x, y, z + 0.21, radius, brass)
    _light(name + "Bulb", "POINT", (x, y, z + 0.195), 5, (1.0, 0.67, 0.34), r=0.04)


def _cubby_run(name, x, y, z, length, height, yaw=0.0, depth=0.38, stock_books=True):
    before = set(bpy.data.objects)
    oak = _oak("ir_bh_library_oak", (0.52, 0.33, 0.16))
    led = _emit("ir_bh_library_led", (1.0, 0.69, 0.38), 9.0)
    levels = max(2, round(height / 0.40))
    bays = max(1, round(length / 0.85))
    pitch = (height - 0.12) / levels
    prims = [("box", 0, depth / 2 - 0.015, height / 2, length, 0.03, height)]
    strips = []
    for j in range(levels + 1):
        zz = 0.08 + j * pitch
        prims.append(("box", 0, 0, zz, length, depth, 0.028))
        if j < levels:
            strips.append(("box", 0, -depth / 2 + 0.025, zz + pitch - 0.025, length - 0.06, 0.012, 0.01))
    for k in range(bays + 1):
        prims.append(("box", -length / 2 + k * length / bays, 0, height / 2, 0.03, depth, height))
    _furniture_bevel(_fl().mesh_object(name + "Frame", [(oak, prims), (led, strips)], bevel=False), 0.002)
    rng = random.Random(130 + round(x * 10 + y))
    books = Books(name + "Books", rng)
    for j in range(levels if stock_books else 0):
        bx = -length / 2 + 0.06
        while bx < length / 2 - 0.06:
            thick = rng.uniform(0.025, 0.049)
            h = min(pitch - 0.05, rng.uniform(0.20, 0.32))
            books.add((bx + thick / 2, -0.04, 0.094 + j * pitch + h / 2), (0.20, thick, h),
                      "spine_out", yaw=-math.pi / 2, lean=rng.uniform(-0.018, 0.018))
            bx += thick + rng.uniform(0.012, 0.025)
    books.flush()
    for obj in set(bpy.data.objects) - before:
        obj.location = (x, y, z)
        obj.rotation_euler.z = yaw
    return books.n


def _gallery(stats):
    ra = _real()
    oak = _oak("ir_bh_gallery_oak", (0.48, 0.31, 0.16))
    for i, y in enumerate((4.0, 10.0, 16.0, 21.0)):
        for side in (-1, 1):
            _pinned("014f3ebc50361692497fe6439b2c112ed3e4ab25", f"BHGalleryArmchair{i}_{side}",
                    2.5 + side * 0.85, y, 4.2, 0 if side < 0 else math.pi, (0.78, 0.78, 0.85))
        _rounded_slab(f"BHGalleryTable{i}", oak, 2.5, y, 4.69, 0.55, 0.55, 0.04, 0.10)
        for dx in (-0.18, 0.18):
            for dy in (-0.18, 0.18):
                _taper_leg(f"BHGalleryTableLeg{i}_{dx}_{dy}", oak, (2.5 + dx, y + dy, 4.203), (2.5 + dx, y + dy, 4.67))
        ra.lib("CupFactory", 270 + i, 2.4, y, 4.71, 0, 0.7)
        _mushroom(f"BHGalleryLamp{i}", 2.64, y + 0.08, 4.71)
        bm = Books(f"BHGalleryTableBooks{i}", random.Random(24 + i))
        for k in range(2):
            bm.add((2.5, y - 0.12, 4.725 + k * 0.025), (0.17, 0.22, 0.025), "flat", yaw=0.1 * k)
        bm.flush()
    for i, y in enumerate((1.2, 7.0, 13.0, 18.2)):
        plant = _pinned("8d2d65e076f99151d8aef9133f9ee23636be9288", f"BHGalleryPlanter{i}", 3.55, y, 4.2, 0, (0.55, 0.55, 1.20))
        _leafmat(plant)
    for i, y in enumerate((7.0, 13.0, 18.6)):
        _cubby_run(f"BHGalleryLibrary{i}", 2.4, y, 4.2, 1.2, 0.75)
    stats["bh_gallery"] = {"armchairs": 8, "reading_tables": 4, "planters": 4, "library_m": 3.6, "deck_top": 4.2, "clear_guardrail_aisle_m": 1.1}


def _perimeter(stats):
    import wall_face
    nf, ef = wall_face.face(ROOM, "N"), wall_face.face(ROOM, "E")
    # Opaque north/east wall runs; south glazing and west openings remain clear.
    count = _cubby_run("BHNorthLibrary", 23.0, nf - 0.20, _furniture_floor(), 30.0, 3.3)
    count += _cubby_run("BHEastLibrary", ef - 0.20, 14.0, _furniture_floor(), 12.0, 3.3, -math.pi / 2)
    stats["bh_perimeter"] = {"north_m": 30, "east_m": 12, "books": count, "faces": [nf, ef]}


def _grinder(x, y, z):
    steel = _flat("ir_bh_grinder_metal", (0.40, 0.42, 0.43), 0.28, 1.0)
    black = _flat("ir_bh_grinder_black", (0.025, 0.025, 0.023), 0.40)
    glass = _flat("ir_bh_grinder_glass", (0.8, 0.72, 0.61), 0.06, transmission=0.92)
    _rounded_slab("BHCafeGrinderBase", black, x, y, z + 0.018, 0.19, 0.24, 0.036, 0.045)
    _furniture_bevel(_fl().mesh_object("BHCafeGrinder", [(steel, [
        ("cyl", (x, y, z + 0.035), (x, y, z + 0.23), 0.074, 32),
        ("cyl", (x, y - 0.07, z + 0.13), (x, y - 0.15, z + 0.12), 0.022, 20)]),
        (glass, [("tap", x, y, z + 0.30, 0.14, 0.10, 0.06, 1.0, 0)]),
        (black, [("cyl", (x, y, z + 0.37), (x, y, z + 0.38), 0.102, 32)])], bevel=False), 0.002)


def _cafe(stats):
    ra = _real()
    oak = _oak("ir_bh_counter_oak", (0.48, 0.355, 0.225))
    st = _flat("ir_bh_stone", (0.78, 0.79, 0.75), 0.22)
    f = _fx("cafe_counter")[0]
    x, y = f["position_m"][:2]
    L, Dp, H = f["size_m"]
    # Widen only toward customers; the rear top edge stays at y6.70, retaining a 0.9 m service aisle.
    y, Dp = 6.255, 0.85
    _cabinet("BHCafeCounter", x, y, L, Dp, 1.025, oak, st)
    for obj in list(bpy.data.objects):
        if obj.name.startswith(("BHCafeCounterOakCase", "BHCafeCounterStoneLip")):
            bpy.data.objects.remove(obj, do_unlink=True)
    _rounded_slab("BHCafeCounterOakCase", oak, x, y, 0.60, L - 0.08, Dp - 0.10, 0.72, 0.34)
    _rounded_slab("BHCafeCounterStoneLip", st, x, y, 0.995, L + 0.04, Dp + 0.04, 0.06, 0.40)
    for obj in list(bpy.data.objects):
        if obj.name.startswith(("BHCafeCounterInset", "BHCafeCounterPanelFrame")):
            bpy.data.objects.remove(obj, do_unlink=True)
    ribs = []
    for k in range(97):
        rx = x - L / 2 + 0.08 + k * 0.04
        dx = max(0.0, abs(rx - x) - (L - 0.08) / 2 + 0.34)
        ry = y - (Dp - 0.10) / 2 + 0.34 - math.sqrt(max(0, 0.34 ** 2 - dx ** 2)) - 0.014
        ribs.append(("cyl", (rx, ry, 0.27), (rx, ry, 0.94), 0.014, 12))
    _fl().mesh_object("BHCafeFlutedFront", [(oak, ribs)], bevel=False)
    led = _emit("ir_bh_counter_underlight", (1, 0.68, 0.34), 8)
    _fl().mesh_object("BHCafeCounterUnderlight", [(led, [("box", x, y - Dp / 2 - 0.02, 0.95, L - 0.80, 0.012, 0.014)])], bevel=False)
    _light("ir_bh_cafe_counter_wash", "AREA", (x, y - 0.45, 0.9), 22, (1, 0.69, 0.38), sx=3.5, sy=0.3)
    _espresso_commercial(3.2, 6.3, 1.025)
    _grinder(2.3, 6.3, 1.025)
    for i in range(5):
        ra.lib("CupFactory", 300 + i, 1.35 + i * 0.13, 6.3, 1.025, 0, 0.7)
    _cabinet("BHCafeBackbar", 2.7, 7.9, 3.4, 0.55, 1.12, oak, st)
    _cubby_run("BHCafeBackbarShelf", 2.7, 8.12, 1.12, 3.4, 0.75, depth=0.28, stock_books=False)
    for row in range(2):
        for col in range(6):
            ra.lib("CupFactory", 340 + row * 6 + col, 1.35 + col * 0.51, 8.07, 1.214 + row * 0.315, 0, 0.75)
    for i in range(3):
        ra.lib("JarFactory", 360 + i, 3.3 + i * 0.26, 7.83, 1.12, 0, 0.8)
    for i in range(4):
        ra.lib("CupFactory", 320 + i, 1.55 + 0.32 * i, 7.85, 1.12, 0, 0.7)
    glass = _flat("ir_bh_pastry_glass", (0.96, 0.98, 1.0), 0.025, transmission=1.0)
    plate = _flat("ir_bh_pastry_plate", (0.81, 0.78, 0.69), 0.23)
    cake = _flat("ir_bh_cake_crumb", (0.48, 0.245, 0.075), 0.72)
    icing = _flat("ir_bh_cake_icing", (0.85, 0.76, 0.57), 0.5)
    _fl().mesh_object("BHCafePastryPlate", [(plate, [("cyl", (4.35, 6.3, 1.025), (4.35, 6.3, 1.045), 0.23, 48)])], bevel=False)
    for i, (dx, dy) in enumerate(((-0.08, -0.08), (-0.08, 0.08), (0.08, -0.08), (0.08, 0.08))):
        _pinned("1c2885ea1bb5a23461ec5561f93dde711ffa8161", f"BHCafeCake{i}",
                4.35 + dx, 6.3 + dy, 1.045, 0, (0.11, 0.11, 0.09))
    _dome("BHCafePastryDome", 4.35, 6.3, 1.045, 0.235, glass)
    _dome("BHCafePastryKnob", 4.35, 6.3, 1.283, 0.025, plate)
    leather = _leather()
    table_oak = _oak("ir_bh_table_oak", (0.39, 0.235, 0.12))
    chair_oak = _oak("ir_bh_chair_oak", (0.52, 0.36, 0.20))
    rng = random.Random(318)
    for k, fixture in enumerate(_fx("cafe_table")):
        tx, ty = fixture["position_m"][:2]
        fz = _furniture_floor()
        finish = _piece_finish(table_oak, f"ir_bh_table_piece_{k}", 301 + k, 0.30 + k * 0.02)
        top = _cafe_table(f"BHCafeTable{k}", tx, ty, finish, fz, radius=0.52)
        for q in range(4):
            a = q * math.pi / 2 + rng.uniform(-0.04, 0.04)
            cx, cy = tx + 0.90 * math.cos(a), ty + 0.90 * math.sin(a)
            frame = _piece_finish(chair_oak, f"ir_bh_chair_wood_{k}_{q}", 410 + 4 * k + q, rng.uniform(0.36, 0.42))
            upholstery = _piece_finish(leather, f"ir_bh_chair_leather_{k}_{q}", 510 + 4 * k + q, rng.uniform(0.49, 0.59))
            _cafe_chair(f"BHCafeChair{k}_{q}", cx, cy, a - math.pi / 2 + rng.uniform(-0.04, 0.04), frame, upholstery, fz)
        ra.lib("CupFactory", 180 + k, tx + 0.22, ty, top, 0, 0.8)
        _mushroom(f"BHCafeTableLamp{k}", tx - 0.12, ty, top)
    for i, sx in enumerate((2.0, 4.0)):
        for dx in (-0.14, 0.14):
            for dy in (-0.14, 0.14):
                _taper_leg(f"BHCafeStoolLeg{i}_{dx}_{dy}", chair_oak, (sx + dx, 5.2 + dy, _furniture_floor()),
                           (sx + dx * 0.8, 5.2 + dy * 0.8, _furniture_floor() + 0.58))
        _fl().mesh_object(f"BHCafeStoolFootrest{i}", [(chair_oak, [("cyl", (sx - 0.13, 5.07, _furniture_floor() + 0.24),
            (sx + 0.13, 5.07, _furniture_floor() + 0.24), 0.014, 16)])], bevel=False)
        ra.soft(f"BHCafeStoolPad{i}", leather, sx, 5.2, _furniture_floor() + 0.61, 0.40, 0.40, 0.10, seed=13 + i)
    stats["bh_cafe"] = {"coffee_missing": 0, "oak_tables": 2, "oak_leather_chairs": 8, "table_lamps": 2,
                         "backbar": 1, "counter_stools": 2, "cake_pieces": 4, "service_aisle_m": 0.905}




def _checkout(stats):
    oak = _oak("ir_bh_checkout_oak", (0.48, 0.30, 0.15))
    x, y, length = 36.5, 3.4, 5.8
    _cabinet("BHCheckout", x, y, length, 0.90, 1.025, oak, oak)
    for obj in bpy.data.objects:
        if obj.name.startswith("BHCheckoutInset"):
            for slot in obj.material_slots:
                slot.material = oak
    black = _flat("ir_bh_pos_black", (0.024, 0.027, 0.028), 0.35)
    screen = _flat("ir_bh_reader_screen", (0.06, 0.11, 0.12), 0.22)
    for i, tx in enumerate((34.6, 36.5, 38.4)):
        _pinned("2029bfb9eca4ab612eb6724916cbff472de47d7b", f"BHCheckoutPOS{i}", tx, y, 1.025, -math.pi / 2, (0.46, 0.28, 0.43))
        _rounded_slab(f"BHCheckoutKeyboard{i}", black, tx, y - 0.29, 1.041, 0.30, 0.13, 0.03, 0.018)
        _rounded_slab(f"BHCheckoutReader{i}", black, tx + 0.43, y - 0.20, 1.105, 0.10, 0.16, 0.16, 0.025)
        _rounded_slab(f"BHCheckoutReaderDisplay{i}", screen, tx + 0.43, y - 0.20, 1.19, 0.074, 0.10, 0.012, 0.008)
        for k in range(3):
            _detail_text(f"BHCheckoutKey{i}_{k}", "1 2 3" if k == 0 else ("4 5 6" if k == 1 else "7 8 9"),
                         (tx + 0.43, y - 0.287, 1.12 - 0.025 * k), 0.012, screen)
        bm = Books(f"BHCheckoutOrders{i}", random.Random(90 + i))
        for k in range(3):
            bm.add((tx - 0.45, y, 1.0425 + k * 0.035), (0.24, 0.32, 0.035), "flat")
        bm.flush()
    _cubby_run("BHCheckoutSideRack", 39.2, 1.35, _furniture_floor(), 0.85, 1.15, -math.pi / 2, depth=0.40)
    stats["bh_checkout"] = {"side_rack": 1, "workstations": 3, "readers": 3, "keyboards": 3, "timber_length_m": length}




def _facade(stats):
    """Replace west envelope skins by framed glazing and load-bearing opaque piers/bands."""
    removed = 0
    for name in (f"{ROOM}.wall", f"{ROOM}.meshed", f"{ROOM}.exterior"):
        obj = bpy.data.objects.get(name)
        if obj is None:
            continue
        obj.data = obj.data.copy()
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        faces = [face for face in bm.faces if all((obj.matrix_world @ v.co).x < 0.14 for v in face.verts)]
        removed += len(faces)
        bmesh.ops.delete(bm, geom=faces, context='FACES')
        bm.to_mesh(obj.data)
        bm.free()
    if removed == 0:
        raise RuntimeError("West facade replacement found no west-facing architecture")
    plaster = _flat("ir_bh_side_pier", (0.86, 0.85, 0.81), 0.65)
    black = _flat("ir_bh_side_frame", (0.035, 0.04, 0.04), 0.35, 0.5)
    glass = _flat("ir_bh_side_glass", (0.96, 0.98, 1.0), 0.025, transmission=1.0)
    glass.node_tree.nodes["Principled BSDF"].inputs["IOR"].default_value = 1.45
    piers = [("box", 0.057, y, _zc() / 2, 0.116, 0.14, _zc()) for y in (0.45, 4.65, 8.85, 13.05, 17.25, 21.45, 25.65)]
    piers += [("box", 0.057, 0.18, _zc() / 2, 0.116, 0.36, _zc()),
              ("box", 0.057, 25.88, _zc() / 2, 0.116, 0.24, _zc())]
    for bottom, top in ((0.0, 0.50), (3.72, 4.45), (7.25, 7.68)):
        piers.append(("box", 0.057, 13.0, (bottom + top) / 2, 0.116, 26.0, top - bottom))
    _fl().mesh_object("BHWestFacadePiers", [(plaster, piers)], bevel=False)
    frames, panes = [], []
    for i in range(6):
        y0, y1 = 0.52 + 4.2 * i, 4.58 + 4.2 * i
        for z0, z1 in ((0.52, 3.70), (4.47, 7.23)):
            panes.append(("box", 0.055, (y0 + y1) / 2, (z0 + z1) / 2, 0.012, y1 - y0, z1 - z0))
            for yy in (y0, (y0 + y1) / 2, y1):
                frames.append(("box", 0.10, yy, (z0 + z1) / 2, 0.035, 0.035, z1 - z0 + 0.04))
            for zz in (z0, z1):
                frames.append(("box", 0.10, (y0 + y1) / 2, zz, 0.035, y1 - y0, 0.035))
    _fl().mesh_object("BHWestFacadeGlass", [(glass, panes)], bevel=False)
    _furniture_bevel(_fl().mesh_object("BHWestFacadeFrames", [(black, frames)], bevel=False), 0.002)
    # A local photo backdrop outside the opened envelope, continuous with the south street treatment.
    img = bpy.data.images.load("/jarvis/project/robomituba/data/venue_refs/bigglass_cards/street_trees_photo.png", check_existing=True)
    mat = bpy.data.materials.new("ir_bh_side_exterior_photo")
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    nodes.clear()
    out = nodes.new("ShaderNodeOutputMaterial")
    emit = nodes.new("ShaderNodeEmission")
    emit.inputs["Strength"].default_value = 0.7
    tex = nodes.new("ShaderNodeTexImage")
    tex.image = img
    links.new(tex.outputs["Color"], emit.inputs["Color"])
    links.new(emit.outputs[0], out.inputs["Surface"])
    me = bpy.data.meshes.new("BHWestExteriorPhoto")
    me.from_pydata([(-0.5, -5, -1.5), (-0.5, 36, -1.5), (-0.5, 36, 10.0), (-0.5, -5, 10.0)], [], [(0, 1, 2, 3)])
    uv = me.uv_layers.new()
    for loop, coord in zip(me.polygons[0].loop_indices, ((0, 0), (1, 0), (1, 1), (0, 1))):
        uv.data[loop].uv = coord
    me.materials.append(mat)
    obj = bpy.data.objects.new("BHWestExteriorPhoto", me)
    bpy.context.scene.collection.objects.link(obj)
    obj["ir_background_only"] = True
    stats["bh_side_facade"] = {"west_faces_removed": removed, "glazing_bays": 12, "bands_z": [[0.52, 3.70], [4.47, 7.23]], "external_photo": img.filepath}


def _sloped_box(name, mat, loc, dims, angle):
    obj = _fl().mesh_object(name, [(mat, [("box", 0, 0, 0, *dims)])], bevel=False)
    obj.location = loc
    obj.rotation_euler.x = angle
    return _furniture_bevel(obj, 0.002)


def _gondola_cheek(name, mat, x, y, base, depth, height):
    profile = [(-depth / 2, base), (depth / 2, base), (0.38, height), (-0.38, height)]
    vertices = [(x + side * 0.027, y + yy, zz) for side in (-1, 1) for yy, zz in profile]
    faces = [(3, 2, 1, 0), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    me = bpy.data.meshes.new(name)
    me.from_pydata(vertices, [], faces)
    me.materials.append(mat)
    obj = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(obj)
    return _furniture_bevel(obj, 0.003)


def _espresso_commercial(x, y, z):
    steel = _flat("ir_bh_espresso_steel", (0.42, 0.44, 0.45), 0.24, 1.0)
    black = _flat("ir_bh_espresso_polymer", (0.024, 0.026, 0.028), 0.36)
    chrome = _flat("ir_bh_espresso_chrome", (0.62, 0.64, 0.65), 0.16, 1.0)
    gauge = _flat("ir_bh_espresso_gauge", (0.83, 0.79, 0.65), 0.3)
    feet = [("cyl", (x + dx, y + dy, z), (x + dx, y + dy, z + 0.065), 0.025, 20)
            for dx in (-0.25, 0.25) for dy in (-0.12, 0.12)]
    _fl().mesh_object("BHCafeCommercialFeet", [(black, feet)], bevel=False)
    _rounded_slab("BHCafeCommercialChassis", steel, x, y + 0.035, z + 0.25, 0.70, 0.40, 0.38, 0.055, edge_width=0.008)
    _rounded_slab("BHCafeCommercialFrontPanel", black, x, y - 0.175, z + 0.29, 0.60, 0.022, 0.18, 0.008)
    _rounded_slab("BHCafeDripTray", chrome, x, y - 0.15, z + 0.055, 0.66, 0.27, 0.035, 0.035)
    parts = []
    for dx in (-0.17, 0.17):
        parts += [("cyl", (x + dx, y - 0.17, z + 0.24), (x + dx, y - 0.24, z + 0.24), 0.048, 32),
                  ("cyl", (x + dx, y - 0.24, z + 0.24), (x + dx, y - 0.24, z + 0.20), 0.041, 24)]
    _fl().mesh_object("BHCafeTwinBrewGroups", [(chrome, parts)], bevel=False)
    handles = [("cyl", (x + dx, y - 0.24, z + 0.23), (x + dx, y - 0.38, z + 0.23), 0.015, 20) for dx in (-0.17, 0.17)]
    _fl().mesh_object("BHCafePortafilterHandles", [(black, handles)], bevel=False)
    rods = [("cyl", (x - 0.31, y - 0.17, z + 0.28), (x - 0.33, y - 0.22, z + 0.12), 0.006, 16),
            ("cyl", (x - 0.33, y - 0.22, z + 0.12), (x - 0.27, y - 0.24, z + 0.09), 0.006, 16)]
    rods += [("cyl", (x - 0.29, y - 0.27 + j * 0.022, z + 0.077), (x + 0.29, y - 0.27 + j * 0.022, z + 0.077), 0.003, 12) for j in range(9)]
    rods += [("cyl", (x - 0.30, y + yy, z + 0.44), (x + 0.30, y + yy, z + 0.44), 0.007, 16) for yy in (-0.09, 0.19)]
    _fl().mesh_object("BHCafeSteamWandAndGrill", [(chrome, rods)], bevel=False)
    _fl().mesh_object("BHCafePressureGauge", [(gauge, [("cyl", (x, y - 0.19, z + 0.32), (x, y - 0.198, z + 0.32), 0.034, 32)]),
                                           (black, [("cyl", (x, y - 0.20, z + 0.32), (x + 0.017, y - 0.20, z + 0.338), 0.002, 10)])], bevel=False)


def _steps(stats):
    oak = _oak("ir_bh_terrace_oak", (0.52, 0.34, 0.18))
    sage = _flat("ir_bh_terrace_sage", (0.23, 0.31, 0.17), 0.85)
    cream = _flat("ir_bh_terrace_cream", (0.64, 0.59, 0.46), 0.85)
    fz = _furniture_floor()
    for i in range(4):
        _rounded_slab(f"BHStep{i}", oak, 34.15 + i * 1.5, 14, fz + 0.09 * (i + 1), 1.5, 12, 0.18 * (i + 1), 0.035)
    # Three uninterrupted runs; table footprints stay on a single tread and leave 0.8 m clear strips.
    for i, (x, tier) in enumerate(((33.78, 0), (35.90, 1), (38.30, 3))):
        base = fz + 0.18 * (tier + 1)
        _rounded_slab(f"BHTerraceSeat{i}", sage, x, 14, base + 0.07, 0.70, 9.8, 0.14, 0.05, edge_width=0.035)
        _rounded_slab(f"BHTerraceBack{i}", sage, x + 0.41, 14, base + 0.39, 0.12, 9.8, 0.50, 0.04, edge_width=0.03)
    for row, (x, tier) in enumerate(((35.275, 1), (37.675, 2))):
        floor = fz + 0.18 * (tier + 1)
        for j, y in enumerate((10.0, 14.0, 18.0)):
            name = f"BHTerraceReadingTable{row}_{j}"
            top = floor + 0.48
            obj = _fl().mesh_object(name + "Top", [(oak, [("cyl", (x, y, top - 0.035), (x, y, top), 0.225, 48)])], bevel=False)
            _furniture_bevel(obj, 0.003)
            _taper_leg(name + "Stem", oak, (x, y, floor + 0.02), (x, y, top - 0.035), 0.075, 0.045)
            _fl().mesh_object(name + "Base", [(oak, [("cyl", (x, y, floor), (x, y, floor + 0.025), 0.17, 32)])], bevel=False)
            _mushroom(f"BHTerraceReadingLamp{row}_{j}", x, y, top, 0.11)
    for i, (x, y) in enumerate(((34.5, 7.15), (36.0, 7.15), (37.5, 7.15), (34.5, 20.85))):
        _rounded_slab(f"BHTerraceCubeBase{i}", oak, x, y, fz + 0.06, 0.48, 0.48, 0.12, 0.05)
        _rounded_slab(f"BHTerraceCubeSeat{i}", cream if i % 2 else sage, x, y, fz + 0.32, 0.55, 0.55, 0.40, 0.075, edge_width=0.025)
    for i, y in enumerate((8.5, 12.4, 16.0, 18.6)):
        _cubby_run(f"BHTerraceCubby{i}", 33.0, y, fz, 1.1, 0.65, -math.pi / 2, depth=0.60)
    stats["bh_steps"] = {"connected_tiers": 4, "long_benches": 3, "bench_length_m": 9.8, "reading_tables": 6,
                          "cube_seats": 4, "book_cubbies": 4, "clear_strips_m": [0.80, 1.08], "end_access_m": 1.1}


def _notebook_flat(name, x, y, z, seed):
    obj = _pinned("0e11918fe7eaf8bdee859494e0d3dfe59d5b2d32", name, x, y, z, 0.0, None)
    R = obj.rotation_euler.to_matrix() @ Matrix.Diagonal(obj.scale)
    points = [R @ Vector(c) for c in obj.bound_box]
    ext = [max(v[k] for v in points) - min(v[k] for v in points) for k in range(3)]
    M = Matrix.Diagonal(tuple(t / max(e, 1e-6) for t, e in zip((0.20, 0.25, 0.014), ext))) @ R
    points = [M @ Vector(c) for c in obj.bound_box]
    cx = (min(v.x for v in points) + max(v.x for v in points)) / 2
    cy = (min(v.y for v in points) + max(v.y for v in points)) / 2
    obj.matrix_world = Matrix.Translation((x - cx, y - cy, z - min(v.z for v in points))) @ M.to_4x4()
    obj["ir_packet_size_m"] = [0.20, 0.25, 0.014]
    return obj


def _pegs(stats):
    oak = _oak("ir_bh_stationery_oak", (0.57, 0.40, 0.23))
    count = 0
    for i, fixture in enumerate(_fx("pegboard_display")):
        x, y = fixture["position_m"][:2]
        fz = _furniture_floor()
        _cubby_run(f"BHStationeryIsland{i}East", x + 0.21, y, fz, 3.5, 0.95, math.pi / 2, depth=0.40)
        _cubby_run(f"BHStationeryIsland{i}West", x - 0.21, y, fz, 3.5, 0.95, -math.pi / 2, depth=0.40)
        top = fz + 1.01
        _rounded_slab(f"BHStationeryIsland{i}Top", oak, x, y, top - 0.03, 0.90, 3.56, 0.06, 0.08)
        for side in (-1, 1):
            for k in range(7):
                for n in range(3):
                    _notebook_flat(f"BHNotebookPacket{i}_{side}_{k}_{n}", x + side * 0.23,
                                   y - 1.38 + k * 0.46, top + n * 0.014, 100 + k + n)
                    count += 1
    stats["bh_pegs"] = {"low_islands": 3, "height_m": 1.01, "real_notebook_packets": count, "packet_size_m": [0.20, 0.25, 0.014]}


def _islands(stats):
    oak = _oak("ir_bh_open_island_oak", (0.52, 0.34, 0.18))
    led = _emit("ir_bh_open_island_led", (1.0, 0.69, 0.38), 10)
    rng = random.Random(531)
    total = 0
    for i, fixture in enumerate(_fx("display_island")):
        x, y = fixture["position_m"][:2]
        L, depth, H = fixture["size_m"]
        fz = _furniture_floor()
        prims = [("box", x, y, fz + 0.07, L - 0.12, depth - 0.12, 0.14),
                 ("box", x, y, 0.59, L, depth, 0.035),
                 ("box", x, y, (H + fz) / 2, L - 0.10, 0.025, H - fz - 0.10)]
        for dx in (-L / 2 + 0.04, L / 2 - 0.04):
            for dy in (-depth / 2 + 0.04, depth / 2 - 0.04):
                prims.append(("box", x + dx, y + dy, (H + fz) / 2, 0.07, 0.07, H - fz))
        _furniture_bevel(_fl().mesh_object(f"BHIsland{i}Body", [(oak, prims)], bevel=False), 0.003)
        _rounded_slab(f"BHIsland{i}OakTopLip", oak, x, y, H - 0.015, L + 0.03, depth + 0.03, 0.07, 0.08)
        strips = [("box", x, y + side * (depth / 2 - 0.03), z, L - 0.16, 0.012, 0.012) for side in (-1, 1) for z in (0.56, 0.93)]
        _fl().mesh_object(f"BHIsland{i}InteriorStrips", [(led, strips)], bevel=False)
        books = Books(f"BHIsland{i}", rng)
        for side in (-1, 1):
            for base in (fz + 0.14, 0.6075):
                for k in range(18):
                    bx = x - 1.75 + k * 3.5 / 17
                    bh = rng.uniform(0.20, 0.30)
                    books.add((bx, y + side * (depth / 2 - 0.12), base + bh / 2), (0.03, 0.16, bh),
                              "face_out", yaw=side * math.pi / 2, tilt=-0.10)
            for base in (fz + 0.14, 0.6075):
                for k in range(4):
                    bh = rng.uniform(0.21, 0.28)
                    books.add((x + side * (L / 2 - 0.14), y - 0.36 + k * 0.24, base + bh / 2),
                              (0.028, 0.17, bh), "face_out", yaw=0 if side > 0 else math.pi, tilt=-0.08)
        for k in range(6):
            for n in range(3):
                books.add((x - 1.5 + k * 0.6, y + (0.22 if k % 2 else -0.22), H + 0.0325 + n * 0.025), (0.20, 0.27, 0.025), "flat")
        total += books.n
        books.flush()
        _mushroom(f"BHIslandLamp{i}", x + 0.9, y, H + 0.02, radius=0.20)
    stats["bh_islands"] = {"islands": 3, "books": total, "open_long_faces": 6, "stocked_open_ends": 6}


def _light_part(stats):
    zc = _zc(); n = 0
    for i in range(5):
        for j in range(4):
            # Café/entrance and cross-aisles remain brighter than the reading terrace and deep aisles.
            energy = (64 if j == 0 else 48) if i == 0 else (25 if i == 4 else (30 if j % 2 else 43))
            _light(f"ir_bh_fill_{i}_{j}", "AREA", (6.0 + 7.0 * i, 3.2 + 6.4 * j, zc - 0.4), energy,
                   (1.0, 0.95, 0.88), sx=2.5, sy=2.5)
            n += 1
    led = bpy.data.materials.get("ir_bh_led")
    if led and led.use_nodes:
        led.node_tree.nodes["Principled BSDF"].inputs["Emission Strength"].default_value = 11.0
    for obj in bpy.data.objects:
        if obj.type == "LIGHT" and obj.name.startswith("ir_bh_tower_"):
            obj.data.energy = 45 * LIGHT
            obj.data.color = (1.0, 0.69, 0.38)
            target = obj.location + Vector((0, 0.35, 0))
            obj.rotation_euler = (target - obj.location).to_track_quat('-Z', 'Y').to_euler()
    if led and led.use_nodes:
        led.node_tree.nodes["Principled BSDF"].inputs["Emission Color"].default_value = (1.0, 0.69, 0.38, 1)
    stats["bh_fill_lights"] = n
    stats["bh_zonal_lighting"] = {"fill_energy_range_w": [25, 64], "shelf_led_strength": 11.0}
    stats["bh_book_variation"] = _S.get("book_metrics", {})


def apply(stats):
    sc = bpy.context.scene
    if sc.get("ir_bookhall_shell") or bpy.data.objects.get(f"{ROOM}.floor") is None:
        return 0
    skip = set((os.environ.get("ROOM_BOOKHALL_SKIP") or "").split(",")); n = 0
    for key, fn in (("clean", _clean), ("facade", _facade), ("floor", _floor), ("ceiling", _ceiling), ("columns", _columns), ("mezz", _mezz), ("towers", _towers), ("gondolas", _gondolas), ("islands", _islands),
                    ("cafe", _cafe), ("pegs", _pegs), ("steps", _steps), ("checkout", _checkout), ("lamps", _lamps), ("plants", _plants), ("gallery", _gallery), ("perimeter", _perimeter), ("backdrop", _backdrop), ("details", _details), ("light", _light_part)):
        if key in skip and key != "clean":
            continue
        try:
            bpy.context.view_layer.update(); fn(stats); n += 1
        except Exception as ex:                                  # noqa: BLE001 -- a part that fails must not sink the kit stage
            import traceback; traceback.print_exc()
            stats[f"bh_{key}_error"] = repr(ex)[:160]
    try:
        _real().report(stats, "bh")
    except Exception:                                            # noqa: BLE001
        pass
    sc["ir_bookhall_shell"] = 1
    return n
