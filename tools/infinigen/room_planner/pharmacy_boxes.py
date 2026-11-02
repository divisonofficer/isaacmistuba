"""Pharmacy stock from Infinigen's own paper-box prop (user 10-21: 'use Infinigen's FoodBoxFactory, swap its albedo texture for generated art').

Switch: env ROOM_PHARMACY_BOXES=1 or kit STYLE["pharmacy_boxes"]. Used by realize._shelf_labels / realize.fill (pharmacy venue only).

FoodBoxFactory is one mesh with one `shader_text*` material (a TEX_IMAGE node: the printed albedo; roughness / normal stay Infinigen's). Its two big faces (normal +-y, 56% of the
image width) share a centre strip of the image, the sides and top a thin strip, so a flat front-face artwork would be cropped. restyle() re-maps the two big faces to the whole image
(upright as seen from outside), points the other faces at the artwork's left edge, swaps the image for a label from data/venue_refs/pharmacy_pack_labels/label_*.png (fallback: the
med_box / otc / care_box prints) and bakes a carton size: carton, blister flat box or tall bottle carton.
"""
from __future__ import annotations

import math
import os
from pathlib import Path

import bpy
from mathutils import Matrix

REF = Path("/jarvis/project/robomituba/data/venue_refs")
SHAPES = (("carton", 5, (0.06, 0.10), (0.04, 0.07), (0.09, 0.16)), ("blister", 2, (0.09, 0.12), (0.02, 0.03), (0.11, 0.15)), ("bottle", 3, (0.04, 0.05), (0.04, 0.05), (0.11, 0.16)))


def enabled():
    from room_planner import proc_assets
    return os.environ.get("ROOM_PHARMACY_BOXES") == "1" or bool(proc_assets.STYLE.get("pharmacy_boxes"))


def label_files():
    fs = sorted((REF / "pharmacy_pack_labels").glob("label_*.png"))
    if not fs:
        for d, pat in (("product_labels_v2", "otc_*.png"), ("product_labels_v2", "care_box_*.png"), ("product_labels", "med_box_*.png")):
            fs += sorted((REF / d).glob(pat))
    return fs


def restyle(o, rng):
    """-> True if `o` (a fresh FoodBoxFactory mesh) now carries a pharmacy label at carton size."""
    files = label_files()
    if not files or o.type != "MESH" or o.data.uv_layers.active is None:
        return False
    img = bpy.data.images.load(str(rng.choice(files)), check_existing=True); img.colorspace_settings.name = "sRGB"
    ok = False
    for slot in o.material_slots:
        m = slot.material
        if m is not None and m.use_nodes and m.name.startswith("shader_text"):
            for nd in m.node_tree.nodes:
                if nd.type == "TEX_IMAGE":
                    nd.image = img; ok = True
    if not ok:
        return False
    me = o.data; uvl = me.uv_layers.active.data
    xs = [v.co.x for v in me.vertices]; zs = [v.co.z for v in me.vertices]
    x0, x1, z0, z1 = min(xs), max(xs), min(zs), max(zs)
    for p in me.polygons:
        big = abs(p.normal.y) > 0.7 and p.area > 0.5 * max(q.area for q in me.polygons)
        for li in p.loop_indices:
            co = me.vertices[me.loops[li].vertex_index].co
            if big:                                           # seen from outside: -y face runs left to right with +x, the +y face with -x
                u = (co.x - x0) / max(x1 - x0, 1e-6)
                uvl[li].uv = (u if p.normal.y < 0 else 1 - u, (co.z - z0) / max(z1 - z0, 1e-6))
            else:
                uvl[li].uv = (0.03, 0.5)
    kind = rng.choices(SHAPES, [s[1] for s in SHAPES])[0]
    d = o.dimensions                                          # the label faces are +-y; the shelf front of a placed product is +x (merch: x = depth, y = width), so scale as (width, depth, height) and then turn the mesh 90 deg about z: label on the front, plain sides
    w_, d_, h_ = (rng.uniform(*kind[2 + i]) for i in range(3))
    o.scale = (w_ / max(d[0], 1e-3), d_ / max(d[1], 1e-3), h_ / max(d[2], 1e-3))
    bpy.ops.object.select_all(action="DESELECT"); o.select_set(True); bpy.context.view_layer.objects.active = o
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    me.transform(Matrix.Rotation(math.pi / 2, 4, "Z")); me.update()
    bpy.context.view_layer.update()
    o["pharmacy_box"] = kind[0]
    return True
