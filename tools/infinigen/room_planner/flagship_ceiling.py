"""Exposed-ceiling services for the large flagship boutique (reference set boutique_large_flagship_01, 2026-10-17): what architecture_pass's
'industrial' archetype lacks -- perforated cable trays on wire hangers, white rectangular ducts, bundled white pipes, concrete beams and
white track rails with white spot heads.

    flagship_services(L, S, zc, at, name, rng, stats)      called by architecture_pass.build() when the archetype has flagship=1

`at(u, v)` maps the room frame (u along the long axis, v across) to world xy; `name(kind)` returns a spawn_asset-style object name.
Each element kind is ONE merged mesh (trays + slots + wires, ducts, pipes, beams, rails + heads), so the object count stays small; the
spot lights are Blender SPOT lights like the existing TrackSpot ones. Heights are scaled down when the ceiling is under 4 m.
"""
from __future__ import annotations

import math

import bpy

from room_planner import proc_boutique_flagship as fl


def flagship_services(L, S, zc, at, name, rng, stats, spot_every=1.6, spot_w=None, fill_w=None):
    import os
    spot_w = float(os.environ.get("FLAGSHIP_SPOT_W", "12")) if spot_w is None else spot_w          # env: spot power (S21: the ref's track spots read strongly)
    fill_w = float(os.environ.get("FLAGSHIP_FILL_W", "450")) if fill_w is None else fill_w          # env: the area fill under the soffit (S21: ceiling blown white)
    _br = os.environ.get("FLAGSHIP_BEAM_RGB")                                                      # env "r,g,b" (linear): dark grey beams / trays like the ref's exposed structure (S21)
    white = fl._flat("ir_fl_white", tuple(float(x) for x in _br.split(",")) if _br else (0.88, 0.87, 0.84), 0.55)
    conc = fl._flat("ir_fl_concrete", (0.6, 0.59, 0.56), 0.9)
    slot = fl._flat("ir_fl_slot", (0.1, 0.1, 0.1), 0.7)
    wire = fl._flat("ir_fl_wire", (0.5, 0.5, 0.52), 0.4, 1.0)
    k = min(1.0, zc / 4.5)
    spot_w = spot_w * (max(zc, 3.0) / 3.0) ** 2                  # a 5 m ceiling needs ~3x the power of a 3 m one (flagship r3: 'far too dark')                                           # vertical offsets scale with the ceiling height
    z_duct, z_tray, z_track = zc - 0.32 * k, zc - 0.7 * k, zc - 0.95 * k
    # run helper: a box along u at cross position v (centre z), length L - 2 * m
    def run(v, z, sy, sz, m=0.2):
        (x0, y0), (x1, y1) = at(m, v), at(L - m, v)
        dx, dy = abs(x1 - x0), abs(y1 - y0)                         # the run's length on its own axis, `sy` across it
        return ("box", (x0 + x1) / 2, (y0 + y1) / 2, z, dx if dx > 1e-9 else sy, dy if dy > 1e-9 else sy, sz)

    # concrete beams across v every 4.5-6 m
    beams, u = [], rng.uniform(3.0, 4.5)
    while u < L - 2.0:
        (cx, cy) = at(u, S / 2)
        horiz = at(u, 0)[0] == at(u, 1)[0]                           # the across axis is y when u runs along x
        beams.append(("box", cx, cy, zc - 0.26 * k, 0.36 if horiz else S, S if horiz else 0.36, 0.52 * k))
        u += rng.uniform(4.5, 6.0)
    if beams:
        fl.mesh_object(name("CeilingBeam"), [(conc, beams)], bevel=False)
    # white rectangular ducts + pipe bundles beside them
    vd = [S * 0.2, S * 0.5, S * 0.8]
    ducts, pipes = [], []
    for v in vd:
        ducts.append(run(v, z_duct - 0.1, 1.0, 0.7 * k))                # big white rectangular ducts, visible in the wides (VLM: 'ducts missing')
        for j in range(rng.choice((3, 4, 5))):
            (x0, y0), (x1, y1) = at(0.2, v + 0.45 + j * 0.09), at(L - 0.2, v + 0.45 + j * 0.09)
            pipes.append(("cyl", (x0, y0, zc - 0.1 - 0.02 * j), (x1, y1, zc - 0.1 - 0.02 * j), rng.uniform(0.028, 0.045), 10))
    fl.mesh_object(name("DuctRun"), [(white, ducts + pipes)], bevel=False)
    # perforated cable trays on wire hangers: U channel + a row of dark slots + hangers every 1.5 m
    trays, slots, wires = [], [], []
    for v in sorted(S * f + rng.uniform(-0.2, 0.2) for f in (0.08, 0.38, 0.7, 0.92)):
        trays += [run(v, z_tray, 0.3, 0.012), run(v - 0.14, z_tray + 0.025, 0.012, 0.05), run(v + 0.14, z_tray + 0.025, 0.012, 0.05)]
        n = int((L - 0.6) / 0.3)
        for q in range(n):
            (sx_, sy_) = at(0.3 + q * 0.3, v)
            for dv in (-0.06, 0.06):
                (px, py) = at(0.3 + q * 0.3, v + dv)
                slots.append(("box", px, py, z_tray + 0.007, 0.08 if at(1, 0)[1] == at(0, 0)[1] else 0.035,
                              0.035 if at(1, 0)[1] == at(0, 0)[1] else 0.08, 0.004))
        for q in range(int((L - 0.6) / 1.5) + 1):
            for dv in (-0.12, 0.12):
                (wx, wy) = at(0.3 + q * 1.5, v + dv)
                wires.append(("cyl", (wx, wy, z_tray), (wx, wy, zc), 0.003, 4))
    fl.mesh_object(name("CableTray"), [(white, trays), (slot, slots), (wire, wires)], bevel=False)
    # white track rails on wires with white spot heads; every head carries a SPOT light
    rails, heads, hw = [], [], []
    for v in (S * 0.2, S * 0.5, S * 0.8):
        rails.append(run(v, z_track, 0.04, 0.035, m=0.6))
        n = max(3, int((L - 1.2) / spot_every))
        for q in range(n):
            cx, cy = at(0.6 + (q + 0.5) * (L - 1.2) / n, v)
            tilt = math.radians(rng.uniform(15, 30)); yaw = rng.uniform(0, 2 * math.pi)
            dx, dy = math.sin(tilt) * math.cos(yaw), math.sin(tilt) * math.sin(yaw)
            heads.append(("cyl", (cx, cy, z_track - 0.02), (cx + 0.16 * dx, cy + 0.16 * dy, z_track - 0.02 - 0.16 * math.cos(tilt)), 0.045, 10))
            ld = bpy.data.lights.new(f"ir_track_spot_{len(heads)}", "SPOT"); ld.energy = spot_w; ld.spot_size = math.radians(35)
            ld.spot_blend = 0.4; ld.shadow_soft_size = 0.03
            lo = bpy.data.objects.new(f"PointLampFactory(track).spawn_asset(fl_{len(heads)})", ld)
            bpy.context.scene.collection.objects.link(lo)
            lo.location = (cx, cy, z_track - 0.2); lo.rotation_euler = (tilt, 0, yaw)
            stats["track_spots"] = stats.get("track_spots", 0) + 1
        for q in range(int((L - 1.2) / 2.0) + 1):
            (wx, wy) = at(0.8 + q * 2.0, v)
            hw.append(("cyl", (wx, wy, z_track), (wx, wy, zc), 0.003, 4))
    fl.mesh_object(name("TrackRail"), [(white, rails + heads), (wire, hw)], bevel=False)
    # large soft AREA lights hidden between the trusses for ambient fill (neutral ~3800 K); the white spot heads stay the visible accents
    n_fill = max(6, min(10, int(L * S / 45.0)))
    nu = max(2, round(math.sqrt(n_fill * L / S))); nv = max(2, math.ceil(n_fill / nu))
    for iu in range(nu):
        for iv in range(nv):
            (x, y) = at((iu + 0.5) * L / nu, (iv + 0.5) * S / nv)
            ld = bpy.data.lights.new(f"ir_fill_{iu}_{iv}", "AREA"); ld.shape = "RECTANGLE"; ld.size = 3.0; ld.size_y = 3.0
            ld.energy = fill_w * (max(zc, 3.0) / 5.0) ** 2; ld.color = (1.0, 0.93, 0.85)
            lo = bpy.data.objects.new(f"PointLampFactory(fill).spawn_asset(fl_{iu}_{iv})", ld); bpy.context.scene.collection.objects.link(lo)
            lo.location = (x, y, zc - 0.3); lo.rotation_euler = (math.pi, 0, 0)
            stats["fill_lights"] = stats.get("fill_lights", 0) + 1
    stats["flagship"] = {"beams": len(beams), "ducts": len(vd), "trays": 4, "slots": len(slots)}
