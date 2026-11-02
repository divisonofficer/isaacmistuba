"""Lighting tune for scenes whose soffits / beams glow evenly from every side (user 10-24: S35 'odd lighting wrapping around the structures'). Hooked from kit_lighting last, only when ROOM_LIGHT_TUNE=1.

  ROOM_WORLD_SCALE=0.4   multiplies every world Background strength (the sky fill that lights every surface from all sides)
  ROOM_SUN_SCALE=0.3     multiplies the ir_real_sun* window area lights (surface_realism's sun: 3-4 kW area lights 9 m wide stood inside the shop) and the big-glass SUN lamp (strength 4)
  ROOM_CARD_EMIT=0.6     the emission strength of the window photo card and ground (default scenes: 2.5)
  ROOM_SPOTIFY=1         the ceiling point lights (PointLampFactory(added | pendant | service | lounge | market)) become wide spot lights pointing down (ROOM_SPOT_DEG, default 80 deg cone, blend 0.5): the
                         same watts, but only the floor / tables under them are lit, so soffit and beam undersides fall into shade instead of glowing
  ROOM_FILL_SCALE=0.7    multiplies those point / spot energies too
Idempotent (a light is converted once)."""
from __future__ import annotations

import math
import os

import bpy

CEIL = ("(added)", "(pendant)", "(service)", "(lounge)", "(market)", "(spot_")


def apply(stats):
    ws = float(os.environ.get("ROOM_WORLD_SCALE") or 1.0); ss = float(os.environ.get("ROOM_SUN_SCALE") or 1.0); fs = float(os.environ.get("ROOM_FILL_SCALE") or 1.0)
    deg = float(os.environ.get("ROOM_SPOT_DEG") or 80.0); spot = os.environ.get("ROOM_SPOTIFY") == "1"
    n_w = n_s = n_p = 0
    ce = os.environ.get("ROOM_CARD_EMIT")
    if ce:                                                               # the street photo card + ground emit like a 90 m wide softbox through the shop front (BIGGLASS_CARD_EMIT 2.5)
        for m in bpy.data.materials:
            if m.use_nodes and not m.get("ir_lt") and m.name.startswith(("ir_bg_card", "ir_bg_groundphoto", "ir_env_card", "ir_env_ground")):
                for nd in m.node_tree.nodes:
                    if nd.type == "BSDF_PRINCIPLED":
                        nd.inputs["Emission Strength"].default_value = float(ce)
                m["ir_lt"] = 1; n_w += 1
    w = bpy.context.scene.world
    if w is not None and w.use_nodes and ws != 1.0 and not w.get("ir_lt"):
        for nd in w.node_tree.nodes:
            if nd.type == "BACKGROUND":
                nd.inputs["Strength"].default_value *= ws; n_w += 1
        w["ir_lt"] = 1
    for o in list(bpy.data.objects):
        if o.type != "LIGHT" or o.get("ir_lt"):
            continue
        d = o.data
        if (o.name.startswith("ir_real_sun") or (d.type == "SUN" and "bigglass" in o.name)) and ss != 1.0:
            d.energy *= ss; o["ir_lt"] = 1; n_s += 1
        elif d.type == "POINT" and any(k in o.name for k in CEIL):
            d.energy *= fs
            if spot:
                nl = bpy.data.lights.new(d.name + "_spot", "SPOT"); nl.energy = d.energy; nl.color = d.color; nl.spot_size = math.radians(deg); nl.spot_blend = 0.5; nl.shadow_soft_size = max(d.shadow_soft_size, 0.08)
                o.data = nl; o.rotation_euler = (0.0, 0.0, 0.0)                                       # a spot shines along its local -Z: straight down
            o["ir_lt"] = 1; n_p += 1
    stats["light_tune"] = {"world": n_w, "sun": n_s, "point": n_p}
    return n_w + n_s + n_p
