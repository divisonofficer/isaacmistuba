"""Upper structure of the airport duty-free hall (docs/airport_duty_free_design_proposal.md). Hooked like clinic_lobby_ceiling, only when ROOM_DUTYFREE=1:

    from airport_ceiling import apply; stats["airport_ceiling"] = apply(plans)

For every room whose venue is 'boutique' (single-room scene): removes the room's own ceiling kit lights, then builds
  * 6 curved champagne ribs across the short axis (arcs of 24 boxes rising 1.6 m at the crown) and a white tile ceiling band between them with soft area lights
  * 2 bronze louver domes (ring of 36 thin slats, r 3 m, rising 1.8 m) with a warm glow disc inside
  * a white wavy mezzanine fascia strip (3 stacked bands) along one long wall at 4 m
Plain geometry + a few lights; nothing outside the hall room is touched. Invented look only: no signs, no text.
"""
from __future__ import annotations

import math
import os

import bpy
from mathutils import Vector

from room_planner import proc_boutique_flagship as fl


def _rooms(plans):
    import room_dressing as rd
    rv = plans.get("room_venues") or {}; sv = (plans.get("style_spec") or {}).get("venue")
    for name, parts in rd._rooms().items():
        if "floor" in parts and "wall" in parts and (rv.get(name) or rv.get(name.replace("/", "-")) or (sv if not rv else None)) == "boutique":
            yield name, parts


def apply(plans):
    if os.environ.get("ROOM_DUTYFREE") != "1":
        return 0
    done = 0
    for name, parts in _rooms(plans):
        fp = [parts["floor"].matrix_world @ Vector(c) for c in parts["floor"].bound_box]
        x0, x1, y0, y1 = min(p.x for p in fp), max(p.x for p in fp), min(p.y for p in fp), max(p.y for p in fp); fz = max(p.z for p in fp)
        zc = max((parts["wall"].matrix_world @ Vector(c)).z for c in parts["wall"].bound_box)
        long_x = (x1 - x0) >= (y1 - y0)
        L, S = (x1 - x0, y1 - y0) if long_x else (y1 - y0, x1 - x0)
        P = (lambda u, v, z: (x0 + u, y0 + v, z)) if long_x else (lambda u, v, z: (x0 + v, y0 + u, z))
        champagne = fl._flat("ir_ap_rib_champagne", (0.82, 0.72, 0.55), 0.35, 0.3); tile = fl._flat("ir_ap_ceiling_tile", (0.9, 0.9, 0.88), 0.7)
        bronze = fl._flat("ir_ap_dome_bronze", (0.38, 0.26, 0.14), 0.3, 0.9); white = fl._flat("ir_ap_fascia_white", (0.93, 0.93, 0.9), 0.35)
        glow = bpy.data.materials.get("ir_ap_dome_glow") or bpy.data.materials.new("ir_ap_dome_glow"); glow.use_nodes = True
        b = glow.node_tree.nodes["Principled BSDF"]; b.inputs["Emission Color"].default_value = (1.0, 0.8, 0.5, 1); b.inputs["Emission Strength"].default_value = 6.0
        top = max(zc, 8.0) - 0.2                                      # soffit height; the hall wants 8-9 m, the room generator decides
        ribs, slab = [], [("box", *((x0 + x1) / 2, (y0 + y1) / 2), top + 0.02, L if long_x else S, S if long_x else L, 0.04)]
        for k in range(6):
            u = L * (k + 0.5) / 6; n = 24
            for j in range(n):
                v = S * (j + 0.5) / n; t = (j + 0.5) / n * 2 - 1
                x, y, z = P(u, v, top - 0.5 + 0.6 * (1 - t * t))
                ribs.append(("box", x, y, z, 0.9 if long_x else S / n * 1.1, S / n * 1.1 if long_x else 0.9, 0.5))
        fl.mesh_object(f"AirportRibsFactory({name}).spawn_asset(ribs)", [(champagne, ribs)], bevel=False)
        fl.mesh_object(f"AirportCeilingFactory({name}).spawn_asset(tile)", [(tile, slab)], bevel=False)
        slats = []
        for dk, du in enumerate((L * 0.3, L * 0.7)):
            cx, cy, _ = P(du, S / 2, 0)
            for k in range(36):
                a = 2 * math.pi * k / 36
                slats.append(("cyl", (cx + 3.0 * math.cos(a), cy + 3.0 * math.sin(a), top - 0.4), (cx + 2.2 * math.cos(a), cy + 2.2 * math.sin(a), top - 0.4 + 1.8), 0.04, 6))
            slats.append(("cyl", (cx, cy, top - 0.35), (cx, cy, top - 0.34), 2.4, 24))
        fl.mesh_object(f"AirportDomeFactory({name}).spawn_asset(louver)", [(bronze, slats)], bevel=False)
        fascia = [("box", *P(L / 2, 0.15, top - 4.0 + 0.45 * i), L * 0.9 if long_x else 0.3, 0.3 if long_x else L * 0.9, 0.35) for i in range(3)]   # wavy look: three stacked bands
        fl.mesh_object(f"AirportFasciaFactory({name}).spawn_asset(band)", [(white, fascia)], bevel=False)
        for k in range(8):                                            # soft fill under the soffit: the hall's own light is gone with the ceiling kit
            u, v = L * (k % 4 + 0.5) / 4, S * (0.3 if k < 4 else 0.7); x, y, _ = P(u, v, 0)
            ld = bpy.data.lights.new(f"ir_ap_fill_{k}", "AREA"); ld.shape = "RECTANGLE"; ld.size = 3.0; ld.size_y = 3.0; ld.energy = 1800.0; ld.color = (1.0, 0.93, 0.82)
            lo = bpy.data.objects.new(f"PointLampFactory(fill).spawn_asset({name}_{k})", ld); bpy.context.scene.collection.objects.link(lo)
            lo.location = (x, y, top - 1.0); lo.rotation_euler = (math.pi, 0, 0)
        print(f"AIRPORT_CEILING {name} top={top:.1f} size={L:.0f}x{S:.0f}", flush=True)
        done += 1
    return done
