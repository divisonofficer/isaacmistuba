"""Ceiling kit for the underground bookstore (reference set bookstore_underground_01): a flat ceiling with wood-veneer panel zones, square recessed
LED panels and linear troffers on the white parts, black rectangular track loops with black spot heads over the feature zones, and hanging black
direction boards. Not an exposed ceiling (that is flagship_ceiling.py).

    bookstore_services(L, S, zc, at, name, rng, stats)      called by architecture_pass.build() when the archetype has bookstore=1

`at(u, v)` maps the room frame (u along the long axis from the entrance, v across) to world xy; `name(kind)` returns a spawn_asset-style object
name. One merged mesh per element kind. Lights: a Blender AREA light per 4th recessed panel (cool white) and a SPOT per track head (warm).
"""
from __future__ import annotations

import math
import os

import bpy

from room_planner import proc_boutique_flagship as fl


def bookstore_services(L, S, zc, at, name, rng, stats, area_w=140.0, spot_w=9.0):
    wood = fl._flat("ir_bk_veneer", (0.56, 0.33, 0.17), 0.42, wood=True)
    black = fl._flat("ir_bk_black", (0.05, 0.05, 0.055), 0.45, 0.7)
    wire = fl._flat("ir_bk_wire", (0.5, 0.5, 0.52), 0.4, 1.0)
    led = fl._flat("ir_bk_led_panel", (0.95, 0.95, 0.95), 0.3)
    b = led.node_tree.nodes["Principled BSDF"]
    b.inputs["Emission Color"].default_value = (1.0, 0.98, 0.94, 1.0); b.inputs["Emission Strength"].default_value = 5.0

    def box(cx_u, cy_v, z, su, sv, sz):                           # a box given in (u, v) room-frame size, mapped to world
        (x, y) = at(cx_u, cy_v); (x1, y1) = at(cx_u + 1, cy_v)
        along_x = abs(x1 - x) > 1e-9                              # u runs along world x
        return ("box", x, y, z, su if along_x else sv, sv if along_x else su, sz)

    ENT = 4.5
    # wood panel zones: the entrance zone and a strip over every second aisle (between island rows, ~1.7 m aisles on a 2.7 m pitch)
    wood_parts, zones = [], [(0.0, ENT + 2.0, 0.6, S - 0.6)]
    v = 1.6 + 0.5 + 1.0 + 0.85 + 2.7                              # first aisle centre (shelf 0.35 + aisle 1.7, island 1.0, half aisle)
    k = 0
    while v < S - 2.2:
        if k % 2 == 0:
            zones.append((ENT + 2.0, L - 1.0, v - 1.5, v + 1.5))
        v += 2.7; k += 1
    for u0, u1, v0, v1 in zones:
        wood_parts.append(box((u0 + u1) / 2, (v0 + v1) / 2, zc - 0.03, u1 - u0, v1 - v0, 0.03))
    fl.mesh_object(name("VeneerCeiling"), [(wood, wood_parts)], bevel=False)

    def in_wood(u, v):
        return any(u0 <= u <= u1 and v0 <= v <= v1 for u0, u1, v0, v1 in zones)

    # recessed square panels on a 2.4 m grid, linear troffers in the white parts
    panels, n_panel = [], 0
    for iu in range(int((L - 1.0) / 2.4) + 1):
        for iv in range(int((S - 1.0) / 2.4) + 1):
            u, v = 1.2 + iu * 2.4, 1.2 + iv * 2.4
            if u > L - 0.6 or v > S - 0.6:
                continue
            z = zc - (0.065 if in_wood(u, v) else 0.012)
            panels.append(box(u, v, z, 0.3, 0.3, 0.012)); n_panel += 1
            if True:                                                                                      # ONE light per panel, sized to the panel (0.3 x 0.3 m) at a quarter of the old 140 W: the sim pairs light and panel 1:1 (user 10-23); same total power as the old one-in-four 1.2 m lights
                (x, y) = at(u, v)
                ld = bpy.data.lights.new(f"ir_bk_panel_{n_panel}", "AREA"); ld.shape = "RECTANGLE"; ld.size = 0.3; ld.size_y = 0.3; ld.energy = area_w / 4.0
                ld.color = (1.0, 0.96, 0.9)
                lo = bpy.data.objects.new(f"PointLampFactory(panel).spawn_asset({n_panel})", ld); bpy.context.scene.collection.objects.link(lo)
                lo.location = (x, y, z - 0.012); lo.rotation_euler = (math.pi, 0, 0)               # just under the panel's face (inside its bbox grown by fixture_tags' 0.12 m), so the panel does not shadow it
    for iu in range(int((L - 3.0) / 4.8)):
        for iv in range(int((S - 3.0) / 3.6)):
            u, v = 3.0 + iu * 4.8 + rng.uniform(-0.2, 0.2), 2.4 + iv * 3.6
            if not in_wood(u, v):
                panels.append(box(u, v, zc - 0.012, 1.2, 0.08, 0.012))
    col = bpy.data.collections.get("LedPanels") or bpy.data.collections.new("LedPanels")            # one object per panel (opticalnav sim: each light pairs 1:1 with its 0.6 m panel; user 10-23): ..._panel_NN, all in the LedPanels collection
    if col.name not in bpy.context.scene.collection.children:
        bpy.context.scene.collection.children.link(col)
    base_name = name("LedPanels")
    for k_, p_ in enumerate(panels):
        po = fl.mesh_object(f"{base_name}_panel_{k_:02d}", [(led, [p_])], bevel=False)
        if po is not None:
            for c_ in list(po.users_collection):
                c_.objects.unlink(po)
            col.objects.link(po)

    # black track loops (rectangles) hung over the entrance zone, spot heads on them
    rails, heads, wires = [], [], []
    u0, u1, v0, v1 = 1.0, ENT + 1.5, S * 0.18, S * 0.82
    zr = zc - 0.4
    for (a0, a1, b0, b1) in ((u0, u1, v0, v0), (u0, u1, v1, v1), (u0, u0, v0, v1), (u1, u1, v0, v1)):
        rails.append(box((a0 + a1) / 2, (b0 + b1) / 2, zr, max(a1 - a0, 0.04), max(b1 - b0, 0.04), 0.04))
    for (a0, a1, b0, b1) in ((u0, u1, v0, v0), (u0, u1, v1, v1)):
        n = max(3, int((a1 - a0) / 0.9))
        for q in range(n):
            u, v = a0 + (q + 0.5) * (a1 - a0) / n, b0
            tilt, yaw = math.radians(rng.uniform(15, 35)), rng.uniform(0, 2 * math.pi)
            (x, y) = at(u, v)
            dx, dy = math.sin(tilt) * math.cos(yaw), math.sin(tilt) * math.sin(yaw)
            heads.append(("cyl", (x, y, zr - 0.03), (x + 0.16 * dx, y + 0.16 * dy, zr - 0.03 - 0.16 * math.cos(tilt)), 0.04, 10))
            ld = bpy.data.lights.new("ir_track_spot_bk", "SPOT"); ld.energy = spot_w; ld.spot_size = math.radians(40); ld.spot_blend = 0.4
            ld.color = (1.0, 0.82, 0.62); ld.shadow_soft_size = 0.03
            lo = bpy.data.objects.new(f"PointLampFactory(track).spawn_asset(bk_{len(heads)})", ld); bpy.context.scene.collection.objects.link(lo)
            lo.location = (x, y, zr - 0.2); lo.rotation_euler = (tilt, 0, yaw)
            stats["track_spots"] = stats.get("track_spots", 0) + 1
    for u in (u0, (u0 + u1) / 2, u1):
        for v in (v0, v1):
            (x, y) = at(u, v); wires.append(("cyl", (x, y, zr), (x, y, zc), 0.003, 4))
    fl.mesh_object(name("TrackLoop"), [(black, rails + heads), (wire, wires)], bevel=False)

    # hanging direction boards on the main cross aisles, two wires each
    boards, bwires = [], []
    for u in (ENT + 3.0, ENT + 3.0 + 2.4 * 4 + 1.8):
        if u > L - 2.0:
            continue
        zb = zc - 0.55
        boards.append(box(u, S / 2, zb, 0.04, 1.4, 0.28))
        for dv in (-0.6, 0.6):
            (x, y) = at(u, S / 2 + dv); bwires.append(("cyl", (x, y, zb + 0.14), (x, y, zc), 0.003, 4))
    if boards:
        fl.mesh_object(name("DirectionBoard"), [(black, boards), (wire, bwires)], bevel=False)
    hang = float(os.environ.get("BOOKSTORE_HANG") or 0.0)         # S24 r4: 'lights hung lower, farther from the ceiling, spreading wide': suspended linear bars over every aisle
    n_hang = 0
    if hang > 0.0:
        bars, hwires, glow = [], [], []
        va = 1.6 + 0.5 + 1.0 + 0.85 + 2.7
        while va < S - 1.5:
            u = ENT + 1.5
            while u < L - 1.5:
                zb = zc - hang
                bars.append(box(u, va, zb, 1.4, 0.1, 0.06)); glow.append(box(u, va, zb - 0.032, 1.3, 0.06, 0.006))
                for du in (-0.55, 0.55):
                    (x, y) = at(u + du, va); hwires.append(("cyl", (x, y, zb), (x, y, zc), 0.003, 4))
                (x, y) = at(u, va)
                ld = bpy.data.lights.new(f"ir_bk_hang_{n_hang}", "AREA"); ld.shape = "SQUARE"; ld.size = 1.2; ld.energy = 55.0; ld.color = (1.0, 0.92, 0.78)
                lo = bpy.data.objects.new(f"PointLampFactory(hang).spawn_asset({n_hang})", ld); bpy.context.scene.collection.objects.link(lo)
                lo.location = (x, y, zb - 0.06); lo.rotation_euler = (math.pi, 0, 0)
                n_hang += 1; u += 3.6
            va += 2.7 * 2
        warm = fl._flat("ir_bk_hang_glow", (1.0, 0.9, 0.75), 0.3); wb = warm.node_tree.nodes["Principled BSDF"]
        wb.inputs["Emission Color"].default_value = (1.0, 0.88, 0.68, 1.0); wb.inputs["Emission Strength"].default_value = 8.0
        fl.mesh_object(name("HangingBars"), [(black, bars), (wire, hwires), (warm, glow)], bevel=False)
    stats["bookstore_ceiling"] = {"wood_zones": len(zones), "led_panels": n_panel, "track_heads": len(heads), "boards": len(boards), "hanging_bars": n_hang}
