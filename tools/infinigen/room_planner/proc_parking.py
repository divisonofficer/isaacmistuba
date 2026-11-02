"""Props for the underground parking level (S28; refs out/room_planner_refs/parking_bldg_01_clean; docs/parking_bldg_design_proposal.md). Front +X (cars: the nose is +X).

  ParkedCarFactory          a generic parked car, 4.1-4.7 x 1.75-1.9 x 1.4-1.7 m: body, tapered cabin, dark glass, four wheels, no logo or readable plate; sedan / hatch / SUV by seed, muted colours
  ColumnWithPlateFactory    a square white-painted column 0.65 x 0.65 x full height (3.0 m default, origin at the floor): a black number plate band (B13...) at 2.2 m, a yellow-black hazard base, and sometimes a red fire cabinet
  TrafficConeFactory        an orange cone 0.7 m with a white reflective band
  BollardFactory            a yellow-black post bollard 0.9 m
  WheelStopFactory          a low concrete wheel stop 1.6 x 0.15 x 0.1 m with a yellow band
  BayLinesFactory           the white painted lines of one row of N bays (2.5 m wide, 5.0 m deep; origin at the row's left end of the back line): thin flat boxes
  FloorArrowFactory         a white directional arrow painted on the floor (flat, 2.2 x 0.6 m)
"""
from __future__ import annotations

import math
import bpy
import os
import random

from room_planner import proc_assets as pa
from room_planner import proc_boutique_flagship as fl
from room_planner.proc_boutique_flagship import mesh_object

COLOURS = ((0.9, 0.9, 0.9), (0.06, 0.06, 0.07), (0.45, 0.46, 0.48), (0.7, 0.72, 0.74), (0.1, 0.15, 0.3), (0.5, 0.08, 0.08), (0.2, 0.22, 0.2), (0.85, 0.85, 0.8))


def _loft(o, rings, slot):
    """Add a closed trapezoid-section hull to object o: rings = [(x, half_width_bottom, half_width_top, z_bottom, z_top)], front/back capped, smooth shaded, material slot `slot`."""
    import bmesh
    bm = bmesh.new(); bm.from_mesh(o.data)
    rs = [[bm.verts.new(v) for v in ((x, -wb, z0), (x, wb, z0), (x, wt, z1), (x, -wt, z1))] for x, wb, wt, z0, z1 in rings]
    fs = [bm.faces.new((a[j], a[(j + 1) % 4], b[(j + 1) % 4], b[j])) for a, b in zip(rs, rs[1:]) for j in range(4)] + [bm.faces.new(reversed(rs[0])), bm.faces.new(rs[-1])]
    bmesh.ops.recalc_face_normals(bm, faces=fs)
    for f in fs:
        f.material_index = slot; f.smooth = True
    bm.to_mesh(o.data); bm.free()


HSSD_INDEX = "/jarvis/project/robomituba/vendor_datasets/hssd_objects/hssd_object_index.json"
_hssd_cars = None


DECAL_DIR = "/jarvis/project/robomituba/data/venue_refs/car_decals"
_atlas = None


def _decal_atlas():
    """Chroma-keyed (pure green #00FF00) side decals -> one RGBA atlas data/venue_refs/car_decals/atlas.png, 4 columns of 512 x 256 cells. -> (path, cols, rows, {set: [cell indices]}) or None
    when there are no decal_<set>_<nn>.png files. Rebuilt when a decal is newer than the atlas."""
    global _atlas
    if os.environ.get("ROOM_CAR_DECALS") == "0":                        # no side lettering at all (dataset rule: no readable company-like names on vehicles)
        return None
    if _atlas is not None:
        return _atlas or None
    from pathlib import Path
    from PIL import Image
    import numpy as np
    files = sorted(Path(DECAL_DIR).glob("decal_*_*.png"))
    if not files:
        _atlas = False
        return None
    cols, cw, ch = 4, 512, 256
    rows = (len(files) + cols - 1) // cols
    sets = {}
    for k, f in enumerate(files):
        sets.setdefault(f.stem.split("_")[1], []).append(k)
    out = Path(DECAL_DIR) / "atlas.png"
    if not out.exists() or out.stat().st_mtime < max(f.stat().st_mtime for f in files):
        at = Image.new("RGBA", (cols * cw, rows * ch), (0, 0, 0, 0))
        for k, f in enumerate(files):
            a = np.asarray(Image.open(f).convert("RGB")).astype(np.float32)
            r_, g_, b_ = a[..., 0], a[..., 1], a[..., 2]
            green = g_ - np.maximum(r_, b_)                              # how much greener than the lettering: 255 on the key, ~0 on dark blue / orange
            alpha = np.clip(1.0 - (green - 40.0) / 120.0, 0.0, 1.0)
            a[..., 1] = np.minimum(g_, np.maximum(r_, b_) + 10.0)         # despill the green fringe
            im = Image.fromarray(np.dstack([a, alpha * 255.0]).astype(np.uint8), "RGBA").resize((cw, ch), Image.LANCZOS)
            at.paste(im, ((k % cols) * cw, (k // cols) * ch))
        at.save(out)
    _atlas = (str(out), cols, rows, sets)
    return _atlas


#: livery buckets = ranges of the object's `ir_livery` number: < 0.3 original paint, then yellow / blue / white + orange stripes / white / silver / black / navy (0.1 each)
LIVERIES = (("keep", 0.30, 0.10), ("yellow", 0.10, 0.35), ("blue", 0.10, 0.45), ("stripe", 0.10, 0.55), ("white", 0.10, 0.65), ("silver", 0.10, 0.75), ("black", 0.10, 0.85), ("navy", 0.10, 0.95))
#: decal set per livery (set, probability it gets one, lettering white)
LIVERY_DECALS = {"yellow": ("school", 1.0, False), "blue": ("delivery", 1.0, True), "stripe": ("auto", 1.0, False), "white": ("delivery", 0.5, False), "silver": ("fleet", 0.6, False),
                 "black": ("delivery", 0.4, True), "navy": ("delivery", 0.5, True)}


def _assign_livery(o, rng):
    """Draw this car's livery + side decal and store them as custom properties (the shared paint shader reads them per object): ir_livery, ir_decal (atlas cell or -1), ir_decal_light."""
    name, _w, centre = rng.choices(LIVERIES, weights=[b[1] for b in LIVERIES])[0]
    o["ir_livery"] = centre; o["ir_decal"] = -1.0; o["ir_decal_light"] = 0.0
    at = _decal_atlas()
    spec = LIVERY_DECALS.get(name)
    if at and spec and rng.random() < spec[1] and at[3].get(spec[0]):
        o["ir_decal"] = float(rng.choice(at[3][spec[0]])); o["ir_decal_light"] = 1.0 if spec[2] else 0.0


OBJV_INDEX = "/jarvis/project/robomituba/vendor_datasets/car_models/objaverse_index.json"
#: user-selected Objaverse CC0/CC-BY cars (2026-10-20): index in objaverse_index.json -> (target length m, nose points to -X in the imported frame, i.e. needs a 180 deg turn). Read from the 6 side views;
#: buses / trucks (62, 64, 68, 86, 101: 7-11 m) are not parked in 2.6 x 5 m bays and stay out of this table.
OBJV_CARS = {19: (4.5, True), 20: (3.0, True), 22: (4.9, True), 23: (5.2, True), 25: (4.8, True), 28: (5.4, True), 30: (5.2, False), 39: (5.2, False), 45: (4.8, True),
             54: (5.9, True), 61: (4.4, False), 70: (5.0, True)}
_objv_entries = None
_objv_meshes = {}


def _objv_car(rng, name):
    """A user-selected Objaverse car: GLB imported once, joined, its length turned onto X (nose +X), scaled to a plausible real length, feet on z = 0, footprint centred; copies share the mesh data."""
    global _objv_entries
    import json
    import sys
    from mathutils import Matrix, Vector
    if _objv_entries is None:
        _objv_entries = json.load(open(OBJV_INDEX))["objects"]
    i = rng.choice(sorted(k for k, v in OBJV_CARS.items() if v[0] <= 5.2 and k not in (70, 39) and str(k) not in os.environ.get("ROOM_CAR_DROP", "").split(",")))                  # 70 is a bus (S28F r6); 39 is "(Wrecked) GMC Yukon" (S28F r8: a crushed white car in the foreground)
    length, flip = OBJV_CARS[i]
    mesh = _objv_meshes.get(i)
    if mesh is None:
        if not hasattr(bpy.ops.import_scene, "gltf"):
            bpy.ops.preferences.addon_enable(module="io_scene_gltf2")
        before = set(bpy.data.objects)
        bpy.ops.import_scene.gltf(filepath=_objv_entries[i]["path"])
        new = [o for o in bpy.data.objects if o not in before]
        ms = [o for o in new if o.type == "MESH"]
        for m in ms:
            m.data = m.data.copy() if m.data.users > 1 else m.data
            m.data.transform(m.matrix_world); m.parent = None; m.matrix_world = Matrix.Identity(4)
        for o in new:
            if o.type != "MESH":
                bpy.data.objects.remove(o, do_unlink=True)
        bpy.ops.object.select_all(action="DESELECT")
        for m in ms:
            m.select_set(True)
        bpy.context.view_layer.objects.active = ms[0]
        if len(ms) > 1:
            bpy.ops.object.join()
        o = bpy.context.view_layer.objects.active
        me = o.data
        if os.environ.get("ROOM_CAR_NORMALS") == "1":                    # S28F r9: jagged black patches on a white car hood = flipped / single-sided faces: consistent outward normals, no backface culling
            import bmesh
            bm_ = bmesh.new(); bm_.from_mesh(me); bmesh.ops.recalc_face_normals(bm_, faces=bm_.faces); bm_.to_mesh(me); bm_.free()
            for mt in me.materials:
                if mt is not None:
                    mt.use_backface_culling = False
        ext = lambda: (Vector((min(v.co[k] for v in me.vertices) for k in range(3))), Vector((max(v.co[k] for v in me.vertices) for k in range(3))))
        lo, hi = ext(); d = hi - lo
        if d.y > d.x:
            me.transform(Matrix.Rotation(-math.pi / 2, 4, "Z")); lo, hi = ext(); d = hi - lo
        if flip:
            me.transform(Matrix.Rotation(math.pi, 4, "Z")); lo, hi = ext(); d = hi - lo
        me.transform(Matrix.Scale(length / d.x, 4)); lo, hi = ext()
        me.transform(Matrix.Translation(-Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, lo.z))))
        me["ir_car_nose_x"] = 1
        _vary_materials(me); me["ir_car_varied"] = 1
        mesh = _objv_meshes[i] = me
        bpy.data.objects.remove(o, do_unlink=True)
    o = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(o)
    o.rotation_mode = "XYZ"
    o["ir_car_src"] = f"objv:{i}"; mesh["ir_car_src"] = f"objv:{i}"
    _assign_livery(o, rng)
    return o


def _hssd_car(rng, name):
    """One HSSD 'car' mesh (CC-BY-NC like the other HSSD props), nose turned to +X (every HSSD car imports nose -Y in Blender: checked on all 6 top views), feet on z = 0, origin at the
    footprint centre. The mesh data is shared by every copy (abo_assets._imported), so the rotation is applied to it once. The 1.1k-triangle Range Rover is picked less often."""
    global _hssd_cars
    import json
    import sys
    from mathutils import Matrix
    if _hssd_cars is None:
        _hssd_cars = [e for e in json.load(open(HSSD_INDEX))["objects"] if e.get("hssd_category") == "car" and os.path.exists(e["path"]) and max(e["extent_m"][0], e["extent_m"][2]) <= 5.2]      # S28F r6: a full-size bus stood in the car park -> passenger cars, SUVs and vans up to 5.2 m only
    if not _hssd_cars:
        return None
    if "/jarvis/project/robomituba/tools/infinigen" not in sys.path:
        sys.path.insert(0, "/jarvis/project/robomituba/tools/infinigen")
    import abo_assets
    drop_ = [x for x in os.environ.get("ROOM_CAR_DROP_HSSD", "").split(",") if x]          # S28F r12: the 1.1k-triangle Range Rover is the pale car with jagged black patches; ROOM_CAR_DROP_HSSD=Range Rover
    pool_ = [c_ for c_ in _hssd_cars if not any(x in str(c_.get("name")) for x in drop_)] or _hssd_cars
    e = rng.choices(pool_, weights=[0.4 if e["triangles"] < 5000 else 1.0 for e in pool_])[0]
    o = abo_assets._import(e, name)
    if not o.data.get("ir_car_nose_x"):
        o.data.transform(Matrix.Rotation(math.pi / 2, 4, "Z"))
        o.data["ir_car_nose_x"] = 1
    if not o.data.get("ir_car_varied"):
        _vary_materials(o.data)
        o.data["ir_car_varied"] = 1
    o["ir_car_src"] = o.data["ir_car_src"] = "hssd:" + str(e.get("name") or e.get("path"))
    _assign_livery(o, rng)
    return o


def _vary_materials(me):
    """Per-car paint on the SHARED car materials (user 2026-10-20, Korean liveries: yellow school van, blue delivery truck, white van with orange diagonal stripes): the PAINT material
    (the largest-area textured one of the mesh; tyres, glass and trim keep theirs) gets a shader branch driven by the object's own Object Info > Random, so every parked copy of one HSSD
    car draws its own colour without duplicating a material: 30 % keep the original paint; then 10 % each yellow / blue / white with orange rear stripes / white / silver / black / navy.
    The flat livery colour keeps the original paint's light-dark detail (x 0.75 + 0.5 x luminance). Stripes are diagonal bands in object space on the rear half, nose = +X."""
    area = {}
    for p_ in me.polygons:
        area[p_.material_index] = area.get(p_.material_index, 0.0) + p_.area
    paint = flat = None
    for i, m in sorted(area.items(), key=lambda kv: -kv[1]):
        mat = me.materials[i] if i < len(me.materials) else None
        if mat is None or not mat.use_nodes:
            continue
        b = next((n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
        if b is not None and b.inputs["Base Color"].links and b.inputs["Transmission Weight"].default_value < 0.2 and b.inputs["Alpha"].default_value > 0.99:
            paint = (mat, b)
            break
        if b is not None and flat is None and b.inputs["Transmission Weight"].default_value < 0.2 and b.inputs["Alpha"].default_value > 0.99 and "glass" not in mat.name.lower() \
                and max(b.inputs["Base Color"].default_value[:3]) > 0.08:           # a flat-colour paint (no texture): bright enough not to be the tyres
            flat = (mat, b)
    if paint is None:
        paint = flat
    if paint is None:
        return
    mat, b = paint
    nt = mat.node_tree; N = nt.nodes; L = nt.links
    if b.inputs["Base Color"].links:
        src = b.inputs["Base Color"].links[0].from_socket
    else:
        rgb = N.new("ShaderNodeRGB"); rgb.outputs[0].default_value = b.inputs["Base Color"].default_value; src = rgb.outputs[0]

    def node(kind, **kw):
        n = N.new(kind)
        for k, v in kw.items():
            setattr(n, k, v)
        return n

    def math(op, a_=None, b_=None, c_=None):
        n = node("ShaderNodeMath", operation=op)
        for k, v in enumerate((a_, b_, c_)):
            if v is None:
                continue
            if isinstance(v, (int, float)):
                n.inputs[k].default_value = v
            else:
                L.new(v, n.inputs[k])
        return n.outputs[0]
    def attr(name):
        n = N.new("ShaderNodeAttribute"); n.attribute_type = "OBJECT"; n.attribute_name = name
        return n.outputs["Fac"]
    r = attr("ir_livery")
    ramp = node("ShaderNodeValToRGB"); ramp.color_ramp.interpolation = "CONSTANT"
    cols = [(0.0, (0, 0, 0, 1)), (0.3, (0.95, 0.62, 0.02, 1)), (0.4, (0.04, 0.22, 0.72, 1)), (0.5, (0.9, 0.9, 0.87, 1)), (0.6, (0.88, 0.88, 0.86, 1)),
            (0.7, (0.5, 0.52, 0.55, 1)), (0.8, (0.025, 0.025, 0.03, 1)), (0.9, (0.03, 0.06, 0.2, 1))]
    el = ramp.color_ramp.elements
    while len(el) < len(cols):
        el.new(0.5)
    for e, (pos, col) in zip(el, cols):
        e.position, e.color = pos, col
    L.new(r, ramp.inputs["Fac"])
    lum = node("ShaderNodeRGBToBW"); L.new(src, lum.inputs["Color"])
    shade = math("MULTIPLY_ADD", lum.outputs["Val"], 0.5, 0.75)
    flat = node("ShaderNodeMix", data_type="RGBA", blend_type="MULTIPLY")
    flat.inputs[0].default_value = 1.0
    L.new(ramp.outputs["Color"], flat.inputs[6]); L.new(shade, flat.inputs[7])
    tc = node("ShaderNodeTexCoord"); sep = node("ShaderNodeSeparateXYZ"); L.new(tc.outputs["Object"], sep.inputs[0])
    xs_ = [v.co.x for v in me.vertices]; zs_ = [v.co.z for v in me.vertices]
    Lc_, Hc_, xc_ = max(xs_) - min(xs_), max(zs_), (max(xs_) + min(xs_)) / 2
    # the livery repaints BODY paint only. A scanned car is often one material for everything, so windows, lamps and tyres must be told apart from the paint by position and by the original texture:
    glass_ = math("MULTIPLY", math("GREATER_THAN", sep.outputs["Z"], 0.5 * Hc_), math("LESS_THAN", lum.outputs["Val"], 0.17))          # a dark pixel in the cabin band = window glass
    lamp_ = math("MULTIPLY", math("GREATER_THAN", math("ABSOLUTE", math("SUBTRACT", sep.outputs["X"], xc_)), 0.43 * Lc_),
                 math("MULTIPLY", math("GREATER_THAN", sep.outputs["Z"], 0.33 * Hc_), math("LESS_THAN", sep.outputs["Z"], 0.62 * Hc_)))       # the front / rear end strip at lamp height: headlights, taillights keep their texture
    low_ = math("LESS_THAN", sep.outputs["Z"], 0.2 * Hc_)                                              # below the sills: tyres, wheels, underbody
    orig_ = math("MINIMUM", math("ADD", math("ADD", glass_, lamp_), low_), 1.0)
    keep = math("MULTIPLY", math("GREATER_THAN", r, 0.3), math("SUBTRACT", 1.0, orig_))                  # 0 = original look, 1 = livery
    m1 = node("ShaderNodeMix", data_type="RGBA"); L.new(keep, m1.inputs[0]); L.new(src, m1.inputs[6]); L.new(flat.outputs[2], m1.inputs[7])
    u = math("MULTIPLY_ADD", sep.outputs["X"], 0.6, math("MULTIPLY", sep.outputs["Z"], 1.2))
    stripe = math("LESS_THAN", math("FRACT", math("MULTIPLY", u, 0.8)), 0.22)
    rear = math("LESS_THAN", sep.outputs["X"], 0.2)
    sel = math("MULTIPLY", math("GREATER_THAN", r, 0.5), math("LESS_THAN", r, 0.6))     # the 'white with stripes' bucket
    mask = math("MULTIPLY", math("MULTIPLY", stripe, rear), sel)
    orange = node("ShaderNodeMix", data_type="RGBA"); orange.inputs[7].default_value = (0.95, 0.38, 0.04, 1)
    L.new(mask, orange.inputs[0]); L.new(m1.outputs[2], orange.inputs[6])
    final = orange.outputs[2]
    at = _decal_atlas()
    if at:                                                                  # side decal: one atlas cell chosen by the object's ir_decal, planar along Y on both flanks (mirrored so it reads from outside)
        path, cols, rows, _sets = at
        xs = [v.co.x for v in me.vertices]; zs = [v.co.z for v in me.vertices]
        Lc, Hc = max(xs) - min(xs), max(zs)
        w = 0.44 * Lc; h = min(w / 2, 0.34 * Hc); xc = (max(xs) + min(xs)) / 2 - 0.10 * Lc; z0 = 0.52 * Hc - h / 2
        di = attr("ir_decal"); light = attr("ir_decal_light")
        nrm = node("ShaderNodeSeparateXYZ"); L.new(node("ShaderNodeTexCoord").outputs["Normal"], nrm.inputs[0])
        side = math("GREATER_THAN", math("ABSOLUTE", nrm.outputs["Y"]), 0.75)
        s = math("MULTIPLY", math("SIGN", sep.outputs["Y"]), -1.0)
        u_loc = math("MULTIPLY_ADD", math("MULTIPLY", math("SUBTRACT", sep.outputs["X"], xc), s), 1.0 / w, 0.5)
        v_loc = math("MULTIPLY_ADD", sep.outputs["Z"], 1.0 / h, -z0 / h)
        inside = math("MULTIPLY", math("MULTIPLY", math("GREATER_THAN", u_loc, 0.0), math("LESS_THAN", u_loc, 1.0)),
                      math("MULTIPLY", math("GREATER_THAN", v_loc, 0.0), math("LESS_THAN", v_loc, 1.0)))
        row = math("FLOOR", math("DIVIDE", math("ADD", di, 0.01), float(cols)))
        col = math("SUBTRACT", math("ADD", di, 0.01), math("MULTIPLY", row, float(cols)))
        uu = math("DIVIDE", math("ADD", col, u_loc), float(cols))
        vv = math("DIVIDE", math("ADD", math("SUBTRACT", float(rows - 1), row), v_loc), float(rows))
        comb = node("ShaderNodeCombineXYZ"); L.new(uu, comb.inputs[0]); L.new(vv, comb.inputs[1])
        img = node("ShaderNodeTexImage"); img.image = bpy.data.images.load(path, check_existing=True); img.interpolation = "Linear"; img.extension = "CLIP"
        L.new(comb.outputs[0], img.inputs["Vector"])
        mix_l = node("ShaderNodeMix", data_type="RGBA"); mix_l.inputs[7].default_value = (0.93, 0.93, 0.93, 1)       # dark-blue lettering -> white on dark / blue bodies
        L.new(light, mix_l.inputs[0]); L.new(img.outputs["Color"], mix_l.inputs[6])
        fac = math("MULTIPLY", math("MULTIPLY", img.outputs["Alpha"], inside), math("MULTIPLY", side, math("GREATER_THAN", di, -0.5)))
        dm = node("ShaderNodeMix", data_type="RGBA"); L.new(fac, dm.inputs[0]); L.new(final, dm.inputs[6]); L.new(mix_l.outputs[2], dm.inputs[7])
        final = dm.outputs[2]
    L.new(final, b.inputs["Base Color"])


class ParkedCarFactory:
    def __init__(self, seed):
        r = random.Random(seed); self.r = r
        self.kind = r.choice(("sedan", "hatch", "suv", "suv", "sedan"))
        self.col = r.choice(COLOURS)

    def spawn_asset(self, i):
        """A real HSSD car (6 meshes, shared across all parked cars) unless PARKING_CARS=proc or the import fails: then the procedural car below."""
        src = os.environ.get("PARKING_CARS", "mix")                    # mix (default) | hssd | objaverse | proc
        if src != "proc":
            try:
                use_objv = src == "objaverse" or (src == "mix" and self.r.random() < 0.55)
                o = (_objv_car if use_objv else _hssd_car)(self.r, f"ParkedCarFactory({i}).spawn_asset({i})")
                if o is not None:
                    return o
            except Exception as ex:                                  # noqa: BLE001 -- the procedural car is the fallback
                print(f"PARKING hssd car failed: {ex!r}"[:200], flush=True)
        return self._proc_spawn(i)

    def _proc_spawn(self, i):
        r, k = self.r, self.kind
        L, W, H = {"sedan": (4.6, 1.82, 1.45), "hatch": (4.1, 1.76, 1.48), "suv": (4.7, 1.9, 1.7)}[k]
        paint = fl._flat(f"ir_car_paint_{int(self.col[0] * 100)}_{int(self.col[1] * 100)}_{int(self.col[2] * 100)}", self.col, 0.25, 0.6); glass = fl._flat("ir_car_glass", (0.04, 0.05, 0.06), 0.05, 0.4)
        tyre = fl._flat("ir_car_tyre", (0.03, 0.03, 0.03), 0.8); chrome = fl._flat("ir_car_trim", (0.7, 0.7, 0.72), 0.25, 1.0); lamp = fl._flat("ir_car_lamp", (0.85, 0.85, 0.8), 0.2)
        zb = 0.2; hb = H * 0.42
        body = [("box", 0, 0, zb + hb / 2, L, W, hb)]
        cab_l = L * (0.5 if k == "suv" else 0.42); cab_h = H - zb - hb; cx = -L * (0.04 if k == "suv" else 0.0) - (0.2 if k == "hatch" else 0.0)
        cabin, wind = [], []                                           # the greenhouse is a lofted hull (see _loft below), not slabs
        body[0] = ("box", 0, 0, zb + hb * 0.35, L, W, hb * 0.7)                                    # lower body
        body.append(("box", L * 0.28, 0, zb + hb * 0.85, L * 0.42, W * 0.96, hb * 0.3))              # hood
        body.append(("box", -L * 0.34, 0, zb + hb * 0.85, L * 0.3, W * 0.96, hb * 0.3))              # boot
        wheels = [("cyl", (sx * L * 0.31, sy * (W / 2 - 0.1), 0.0), (sx * L * 0.31, sy * (W / 2 - 0.1) + 0.0, 0.0), 0.0, 6) for sx in (1, -1) for sy in (1, -1)]
        wheels = [("cyl", (sx * L * 0.31, sy * (W / 2 - 0.2), 0.33), (sx * L * 0.31, sy * (W / 2 + 0.02), 0.33), 0.33, 14) for sx in (1, -1) for sy in (1, -1)]
        lamps = [("box", L / 2 + 0.005, sy * W * 0.34, zb + hb * 0.78, 0.02, 0.28, 0.1) for sy in (1, -1)]
        trim = [("box", L / 2 + 0.01, 0, zb + hb * 0.35, 0.02, W * 0.5, 0.06)]
        arch = fl._flat("ir_car_arch", (0.02, 0.02, 0.022), 0.9)                              # dark wheel wells: a disc a little larger than the tyre, flush on the body side
        arches = [("cyl", (sx * L * 0.31, sy * (W / 2 - 0.04), 0.39), (sx * L * 0.31, sy * (W / 2 + 0.006), 0.39), 0.385, 18) for sx in (1, -1) for sy in (1, -1)]
        hubs = [("cyl", (sx * L * 0.31, sy * (W / 2 + 0.015), 0.33), (sx * L * 0.31, sy * (W / 2 + 0.03), 0.33), 0.16, 12) for sx in (1, -1) for sy in (1, -1)]
        o = mesh_object(f"ParkedCarFactory({i}).spawn_asset({i})", [(paint, body + cabin), (glass, wind), (tyre, wheels), (lamp, lamps), (chrome, trim + hubs), (arch, arches)], bevel=True)
        zbase, zt = zb + hb * 0.98, H
        st = {"sedan": ((0.0, 0.45, 0.42, zbase + 0.05), (0.24, 0.45, 0.36, zt - 0.02), (0.6, 0.45, 0.36, zt), (1.0, 0.45, 0.40, zbase + 0.06)),
              "hatch": ((0.0, 0.45, 0.40, zt - 0.28), (0.14, 0.45, 0.36, zt - 0.02), (0.64, 0.45, 0.36, zt), (1.0, 0.45, 0.40, zbase + 0.08)),
              "suv": ((0.0, 0.46, 0.43, zt - 0.14), (0.08, 0.46, 0.40, zt - 0.02), (0.84, 0.46, 0.40, zt), (1.0, 0.46, 0.42, zbase + 0.12))}[k]
        x_rear = cx - cab_l / 2
        _loft(o, [(x_rear + u * cab_l, wb * W, wt * W, zbase, zz) for u, wb, wt, zz in st], 0)                                   # roof + pillars in body paint
        _loft(o, [(x_rear + u * cab_l, wb * W + 0.012, wt * W + 0.012, zbase + 0.1, max(zbase + 0.2, zz - 0.07)) for u, wb, wt, zz in st], 1)   # window band, a little proud
        return o


class ColumnWithPlateFactory:
    def __init__(self, seed):
        self.r = random.Random(seed); self.fire = self.r.random() < 0.35
        self.plate = self.r.choice(("B1", "B2", "B3", "B11", "B12", "B13", "B14", "B15", "A12", "A13", "A14", "C7"))

    def spawn_asset(self, i, H=3.0):
        w = fl._flat("ir_pk_column", (0.88, 0.88, 0.86), 0.7); yel = fl._flat("ir_pk_yellow", (0.9, 0.75, 0.1), 0.5); blk = fl._flat("ir_pk_black", (0.04, 0.04, 0.045), 0.6); red = fl._flat("ir_pk_fire", (0.7, 0.1, 0.08), 0.4)
        p = pa.PRINT_ROOT / f"parkplate_{self.plate}.png"
        plate = pa._printed(p, (0.9, 0.9, 0.9), 0.5) if p.exists() else blk
        groups = [(w, [("box", 0, 0, H / 2, 0.65, 0.65, H)]), (plate, [("box", 0.33, 0, 2.25, 0.01, 0.55, 0.28), ("box", 0, 0.33, 2.25, 0.55, 0.01, 0.28)])]
        stripes = [("box", 0.33, y, 0.25, 0.012, 0.1, 0.5) for y in (-0.25, 0.0, 0.25)]
        groups.append((yel, [("box", 0.331, 0.0, 0.25, 0.01, 0.65, 0.5)])); groups.append((blk, stripes))
        if self.fire:
            groups.append((red, [("box", 0.34, 0.12, 1.3, 0.04, 0.3, 0.5)]))
        return mesh_object(f"ColumnWithPlateFactory({i}).spawn_asset({i})", groups, bevel=False)


class TrafficConeFactory:
    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        o = fl._flat("ir_cone_orange", (0.95, 0.35, 0.05), 0.5); w = fl._flat("ir_cone_white", (0.95, 0.95, 0.93), 0.35); bk = fl._flat("ir_cone_base", (0.05, 0.05, 0.05), 0.6)
        return mesh_object(f"TrafficConeFactory({i}).spawn_asset({i})", [(o, [("cyl", (0, 0, 0.04), (0, 0, 0.7), 0.1, 14)]), (w, [("cyl", (0, 0, 0.32), (0, 0, 0.45), 0.065, 14)]), (bk, [("box", 0, 0, 0.02, 0.36, 0.36, 0.04)])], bevel=False)


class BollardFactory:
    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        y = fl._flat("ir_bol_yellow", (0.9, 0.75, 0.1), 0.5); b = fl._flat("ir_bol_black", (0.04, 0.04, 0.045), 0.6)
        return mesh_object(f"BollardFactory({i}).spawn_asset({i})", [(y, [("cyl", (0, 0, 0.0), (0, 0, 0.9), 0.045, 12)]), (b, [("cyl", (0, 0, 0.3), (0, 0, 0.42), 0.0455, 12), ("cyl", (0, 0, 0.6), (0, 0, 0.72), 0.0455, 12)])], bevel=False)


class WheelStopFactory:
    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        c = fl._flat("ir_ws_concrete", (0.6, 0.6, 0.58), 0.8); y = fl._flat("ir_ws_yellow", (0.9, 0.75, 0.1), 0.5)
        return mesh_object(f"WheelStopFactory({i}).spawn_asset({i})", [(c, [("box", 0, 0, 0.05, 0.15, 1.6, 0.1)]), (y, [("box", 0, -0.55, 0.101, 0.15, 0.2, 0.004), ("box", 0, 0.55, 0.101, 0.15, 0.2, 0.004)])], bevel=False)


def _line_mat():
    """Paint for bay lines and arrows: a plain bright white (no surface-detail noise: _flat's procedural detail greyed the 14 cm lines into the polished concrete, S28F 'no white bay lines at all')."""
    m = bpy.data.materials.get("ir_pk_line")
    if m is None:
        m = bpy.data.materials.new("ir_pk_line"); m.use_nodes = True
        b = m.node_tree.nodes["Principled BSDF"]; b.inputs["Base Color"].default_value = (0.9, 0.9, 0.88, 1); b.inputs["Roughness"].default_value = 0.45
    return m


class BayLinesFactory:
    N = 6

    def __init__(self, seed):
        self.r = random.Random(seed); self.n = self.N

    def spawn_asset(self, i):
        wl = _line_mat()
        n, bw, bd = self.n, 2.6, 5.0
        parts = [("box", 0.0, n * bw / 2, 0.003, 0.15, n * bw, 0.006)]                          # the back line
        parts += [("box", bd / 2, k * bw, 0.003, bd, 0.15, 0.006) for k in range(n + 1)]       # the side lines
        return mesh_object(f"BayLinesFactory({i}).spawn_asset({i})", [(wl, parts)], bevel=False)


class FloorArrowFactory:
    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        wl = _line_mat()
        o = mesh_object(f"FloorArrowFactory({i}).spawn_asset({i})", [(wl, [("box", -0.35, 0, 0.002, 1.5, 0.22, 0.004), ("box", 0.55, 0.0, 0.002, 0.04, 0.04, 0.004), ("box", 0.7, 0.0, 0.002, 0.3, 0.55, 0.004)])], bevel=False)
        o.scale = (1.5, 1.5, 1.0)                                  # S28 r6 'no floor direction arrows': 3.3 x 0.9 m, bright
        return o
