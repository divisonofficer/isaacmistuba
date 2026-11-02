"""Lift the near-black Infinigen leaf albedo (user 10-21, P2b balcony: 'the plants are black, no texture').

Infinigen's `shader_monocot*` colour ramp holds two stops of ~(0.05, 0.06, 0.013) linear: a 4-5 % green albedo, which renders almost black, most of all against a bright backdrop. Real green
leaves reflect ~10-15 % in green. Each ramp stop is multiplied by LIFT (default 2.4) and the light stop gets a yellower, brighter tone (x1.35 red, x1.2 green) so the blade shows a tonal
variation instead of one flat dark tone. Idempotent (`leaf_lift` custom property). Off with ROOM_PLANT_LIFT=0; ROOM_PLANT_LIFT=<x> sets the factor.

    from plant_leaf_lift import apply; stats["plant_leaf_lift"] = apply()
"""
from __future__ import annotations

import os

import bpy


def apply():
    k = float(os.environ.get("ROOM_PLANT_LIFT", "2.4"))
    if k <= 0:
        return 0
    n = 0
    for m in bpy.data.materials:
        if not m.use_nodes or not m.name.startswith("shader_monocot") or m.get("leaf_lift"):
            continue
        for nd in m.node_tree.nodes:
            if nd.type != "VALTORGB":
                continue
            for e in nd.color_ramp.elements:
                r, g, b, a = e.color
                lit = e.position >= 0.5
                e.color = (min(1.0, r * k * (1.35 if lit else 1.0)), min(1.0, g * k * (1.2 if lit else 1.0)), min(1.0, b * k), a)
        m["leaf_lift"] = 1; n += 1
    return n
