"""Ceiling drapes for the rooftop restaurant: white sheer fabric swags hung between roof trusses (reference rooftop_restaurant_01 img 03, 05, 06).

    make_swag(p0, p1, width, slack=1.35, frames=70, name="Swag") -> object      one sheet pinned at both ends, settled by Blender's cloth solver
    drape_services(L, z_anchor, v_centre, anchors, at, name, rng, stats)         swags between every second pair of truss anchors

The sheet starts as an arch (arc length = slack x span) over the two anchor lines, both end rows pinned by POSITION (not by z as proc_assets._drape),
gravity pulls the middle down into a swag. The result is BAKED to a mesh (modifier applied, cache dropped): never leave a CLOTH modifier in the
scene, frame_set at render time would re-simulate. Silk-like settings (mass 0.15, low bending 0.2). ~9k triangles per swag.
"""
from __future__ import annotations

import math
import random

import bmesh
import bpy
from mathutils import Vector


def _fabric():
    m = bpy.data.materials.get("ir_drape_fabric")
    if m is not None:
        return m
    m = bpy.data.materials.new("ir_drape_fabric"); m.use_nodes = True
    b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (0.93, 0.91, 0.86, 1); b.inputs["Roughness"].default_value = 0.85
    if "Sheen Weight" in b.inputs:
        b.inputs["Sheen Weight"].default_value = 0.0
    return m


def make_swag(p0, p1, width=1.8, slack=1.35, frames=70, name="Swag", nu=96, nv=32, seed=0):
    sc, vl = bpy.context.scene, bpy.context.view_layer
    a, b = Vector(p0), Vector(p1)
    span = (b - a).length
    along = (b - a).normalized()
    across = Vector((-along.y, along.x, 0)).normalized()
    arc = span * slack
    # arch: parameter s in [0, 1] along the span; height bump h so that the arc length is ~ slack x span (a sine bump: L ~ span (1 + (pi h / span)^2 / 4))
    h = span * math.sqrt(max(slack - 1.0, 0.01)) * 2.0 / math.pi
    bm = bmesh.new(); rows = []
    for i in range(nu + 1):
        s = i / nu
        row = []
        for j in range(nv + 1):
            t = j / nv - 0.5
            p = a + along * (s * span) + across * (t * width) + Vector((0, 0, h * math.sin(math.pi * s)))
            row.append(bm.verts.new(p))
        rows.append(row)
    for i in range(nu):
        for j in range(nv):
            bm.faces.new((rows[i][j], rows[i + 1][j], rows[i + 1][j + 1], rows[i][j + 1]))
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free(); me.materials.append(_fabric())
    o = bpy.data.objects.new(name, me); sc.collection.objects.link(o)
    vg = o.vertex_groups.new(name="ir_pin")
    vg.add([v.index for v in me.vertices if (v.co - a).dot(along) < 0.02 * span or (v.co - a).dot(along) > 0.98 * span], 1.0, "REPLACE")
    cm = o.modifiers.new("ir_cloth", "CLOTH"); st = cm.settings
    st.quality = 5; st.mass = 0.15; st.tension_stiffness = st.compression_stiffness = 6.0; st.shear_stiffness = 5.0; st.bending_stiffness = 0.2
    st.air_damping = 1.6; st.vertex_group_mass = "ir_pin"
    cm.collision_settings.use_collision = False; cm.collision_settings.use_self_collision = False
    cm.point_cache.frame_start = 1; cm.point_cache.frame_end = frames
    f0 = sc.frame_current
    for f in range(1, frames + 1):
        sc.frame_set(f)
    bpy.ops.object.select_all(action="DESELECT"); vl.objects.active = o; o.select_set(True)
    bpy.ops.object.modifier_apply(modifier="ir_cloth")
    o.vertex_groups.remove(o.vertex_groups["ir_pin"])
    for p in o.data.polygons:
        p.use_smooth = True
    sc.frame_set(f0)
    return o


def drape_services(L, z_anchor, v_centre, anchors, at, name, rng, stats, frames=70):
    """Swags between every second pair of truss anchors (anchors = [(u, z)] from rooftop_shell, sorted by u), alternating sides of the ridge."""
    us = [u for u, _ in anchors]
    made = 0
    for k in range(0, len(us) - 1, 2):
        side = -1.0 if (k // 2) % 2 == 0 else 1.0
        vc = v_centre + side * rng.uniform(1.2, 2.2)
        p0 = (*at(us[k], vc), z_anchor + rng.uniform(-0.1, 0.1)); p1 = (*at(us[k + 1], vc), z_anchor + rng.uniform(-0.1, 0.1))
        make_swag(p0, p1, width=rng.uniform(1.6, 2.2), slack=rng.uniform(1.25, 1.45), frames=frames, name=name("DrapeSwag"), seed=rng.randrange(1 << 20))
        made += 1
    stats["rooftop_drapes"] = made
