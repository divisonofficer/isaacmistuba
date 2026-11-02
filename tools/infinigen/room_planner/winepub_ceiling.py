"""Ceiling kit for the underground wine pub (reference set wine_pub_underground_01): a low white-plaster ceiling over the seating zone, a recessed (higher)
bar zone with EXPOSED black ducts, steel beams and cable runs, black track spots, and a mirror ball + silver spheres (hung via proc_winepub).

    winepub_services(L, S, zc, at, name, rng, stats, ceiling_items=())     called by architecture_pass.build() when the archetype has winepub=1

`at(u, v)` maps the room frame (u along the long axis from the entrance, v across) to world xy. The room's own ceiling is kept (it is the white
plaster); a soffit box lowers it over the seating zone (u < L - 3.6), and the bar zone shows the dark exposed services under a black void plane.
Lights: 5-6 warm SPOTs on a track over the bar and tables (low power: the pub is dark), emissive fairy bulbs live in proc_winepub.BottleRow.
"""
from __future__ import annotations

import math

import bpy

from room_planner import proc_boutique_flagship as fl


def winepub_services(L, S, zc, at, name, rng, stats, ceiling_items=(), spot_w=7.0):
    plaster = fl._flat("ir_wp_plaster", (0.62, 0.6, 0.56), 0.85)
    black = fl._flat("ir_wp_black_service", (0.03, 0.03, 0.034), 0.55, 0.4)
    wire = fl._flat("ir_wp_wire_black", (0.04, 0.04, 0.045), 0.5, 0.5)
    drop = 0.3                                                    # the seating zone's soffit hangs 30 cm below the room ceiling
    sx_end = L - 3.6

    def box(u0, u1, v0, v1, z, th):
        (xa, ya), (xb, yb) = at(u0, v0), at(u1, v1)
        return ("box", (xa + xb) / 2, (ya + yb) / 2, z, abs(xb - xa), abs(yb - ya), th)

    fl.mesh_object(name("Soffit"), [(plaster, [box(0.05, sx_end, 0.05, S - 0.05, zc - drop - 0.025, 0.05)])], bevel=False)
    # S23 r5 'ceiling plain dark brown, no detail': walnut battens + cross beams under the soffit, a warm LED cove along its edge, small recessed downlights, an upward wash on the exposed zone
    walnut = fl._flat("ir_wp_walnut", (0.22, 0.12, 0.07), 0.45, wood=True); cove = fl._flat("ir_wp_cove", (1.0, 0.75, 0.45), 0.3)
    cb = cove.node_tree.nodes["Principled BSDF"]; cb.inputs["Emission Color"].default_value = (1.0, 0.72, 0.4, 1); cb.inputs["Emission Strength"].default_value = 9.0
    zb = zc - drop - 0.06
    slats = [box(0.1, sx_end - 0.05, v - 0.03, v + 0.03, zb, 0.06) for v in [0.3 + 0.32 * k for k in range(int((S - 0.6) / 0.32) + 1)] if v < S - 0.3]
    xbeams = [box(u - 0.05, u + 0.05, 0.1, S - 0.1, zb - 0.04, 0.1) for u in [1.2 + 2.4 * k for k in range(int((sx_end - 1.0) / 2.4) + 1)] if u < sx_end - 0.3]
    fl.mesh_object(name("SoffitBattens"), [(walnut, slats + xbeams)], bevel=False)
    fl.mesh_object(name("SoffitCove"), [(cove, [box(sx_end - 0.12, sx_end - 0.04, 0.2, S - 0.2, zc - drop - 0.04, 0.03)] + [box(0.2, sx_end - 0.1, vv, vv + 0.04, zc - drop - 0.04, 0.03) for vv in (0.12, S - 0.16)])], bevel=False)
    dl = []
    for iu in range(int((sx_end - 1.0) / 1.7) + 1):
        for iv in range(int((S - 1.0) / 1.7) + 1):
            u, v = 1.0 + iu * 1.7, 0.9 + iv * 1.7
            if u < sx_end - 0.3 and v < S - 0.4:
                dl.append(box(u - 0.05, u + 0.05, v - 0.05, v + 0.05, zc - drop - 0.12, 0.012))
    fl.mesh_object(name("SoffitDownlights"), [(cove, dl)], bevel=False)
    xu, yu = at(sx_end + 0.4, S / 2)
    ldw = bpy.data.lights.new("ir_wp_wash", "AREA"); ldw.shape = "RECTANGLE"; ldw.size = 1.0; ldw.size_y = S * 0.8; ldw.energy = 90.0; ldw.color = (1.0, 0.78, 0.55)
    low = bpy.data.objects.new("PointLampFactory(wash).spawn_asset(wp_wash)", ldw); bpy.context.scene.collection.objects.link(low)
    low.location = (xu, yu, zc - 0.55); low.rotation_euler = (0, 0, 0)
    # the exposed zone: a black void plane just under the ceiling, ducts / beams / pipes / cable trays in it
    void = [box(sx_end, L - 0.05, 0.05, S - 0.05, zc - 0.03, 0.02)]
    ducts, beams, cables = [], [], []
    for v in (S * 0.3, S * 0.68):
        a, b = at(sx_end + 0.2, v), at(L - 0.2, v)
        ducts.append(("box", (a[0] + b[0]) / 2, (a[1] + b[1]) / 2, zc - 0.28, abs(b[0] - a[0]) + 0.5 * (abs(b[0] - a[0]) < 1e-6), abs(b[1] - a[1]) + 0.5 * (abs(b[1] - a[1]) < 1e-6), 0.3))
    for u in (sx_end + 0.8, sx_end + 2.1, L - 0.6):
        a, b = at(u, 0.1), at(u, S - 0.1)
        beams.append(("box", (a[0] + b[0]) / 2, (a[1] + b[1]) / 2, zc - 0.12, abs(b[0] - a[0]) + 0.2 * (abs(b[0] - a[0]) < 1e-6), abs(b[1] - a[1]) + 0.2 * (abs(b[1] - a[1]) < 1e-6), 0.2))
    for k in range(5):
        v = S * (0.12 + 0.19 * k)
        a, b = at(sx_end + 0.1, v), at(L - 0.1, v)
        cables.append(("cyl", (*a, zc - 0.18), (*b, zc - 0.18 - 0.03 * (k % 2)), 0.012, 6))
    fl.mesh_object(name("ExposedServices"), [(black, void + ducts + beams), (wire, cables)], bevel=False)
    # black track over the bar zone with warm spot heads
    rails, heads = [], []
    v_t = S * 0.5
    a, b = at(sx_end + 0.3, v_t), at(L - 0.6, v_t)
    zr = zc - 0.22
    rails.append(("cyl", (*a, zr), (*b, zr), 0.015, 6))
    n = 5
    for q in range(n):
        u = sx_end + 0.3 + (q + 0.5) * (L - 0.9 - sx_end) / n
        x, y = at(u, v_t)
        tilt, yaw = math.radians(rng.uniform(15, 30)), rng.uniform(0, 2 * math.pi)
        heads.append(("cyl", (x, y, zr - 0.02), (x + 0.15 * math.sin(tilt) * math.cos(yaw), y + 0.15 * math.sin(tilt) * math.sin(yaw), zr - 0.02 - 0.15 * math.cos(tilt)), 0.04, 8))
        ld = bpy.data.lights.new("ir_track_spot_wp", "SPOT"); ld.energy = spot_w; ld.spot_size = math.radians(38); ld.spot_blend = 0.5
        ld.color = (1.0, 0.78, 0.5); ld.shadow_soft_size = 0.03
        lo = bpy.data.objects.new(f"PointLampFactory(track).spawn_asset(wp_{q})", ld); bpy.context.scene.collection.objects.link(lo)
        lo.location = (x, y, zr - 0.17); lo.rotation_euler = (tilt, 0, yaw)
        stats["track_spots"] = stats.get("track_spots", 0) + 1
    fl.mesh_object(name("TrackRail"), [(black, rails + heads)], bevel=False)
    # warm ambient fill, very low: two AREA lights above the soffit edge so the pub is dark but not black
    for k, u in enumerate((L * 0.25, L * 0.62)):
        x, y = at(u, S / 2)
        ld = bpy.data.lights.new(f"ir_wp_fill_{k}", "AREA"); ld.shape = "RECTANGLE"; ld.size = 2.5; ld.size_y = 2.5; ld.energy = 55.0; ld.color = (1.0, 0.8, 0.58)
        lo = bpy.data.objects.new(f"PointLampFactory(fill).spawn_asset(wp_f{k})", ld); bpy.context.scene.collection.objects.link(lo)
        lo.location = (x, y, zc - drop - 0.06); lo.rotation_euler = (math.pi, 0, 0)
    # amber pools: low warm POINT lights at floor level along the bottle-row line and at the bar (the bottles and fairy lights glow, the room needs their light)
    for k, v in enumerate([S * f for f in (0.15, 0.4, 0.6, 0.85)]):
        x, y = at(L - 3.3, v)
        ld = bpy.data.lights.new(f"ir_wp_amber_{k}", "POINT"); ld.energy = 18.0; ld.color = (1.0, 0.62, 0.28); ld.shadow_soft_size = 0.2
        lo = bpy.data.objects.new(f"PointLampFactory(amber).spawn_asset(wp_a{k})", ld); bpy.context.scene.collection.objects.link(lo)
        lo.location = (x, y, 0.6)
    stats["winepub_amber_lights"] = 4
    # mirror ball and silver sphere clusters (layout 'ceiling' entries), hung from the soffit
    try:
        from room_planner import proc_winepub as wp
        for k, e in enumerate(ceiling_items):
            cls = wp.MirrorBallFactory if e["cat"] == "mirror_ball" else wp.SilverSphereClusterFactory
            o = cls(rng.randrange(1 << 20)).spawn_asset(k)
            o.location = (e["x"], e["y"], zc - drop - 0.05)
    except Exception as ex:                                       # noqa: BLE001 -- decor must not fail the scene
        stats["winepub_ceiling_error"] = str(ex)[:80]
    stats["winepub_ceiling"] = {"soffit_to": round(sx_end, 1), "spots": n, "items": len(ceiling_items)}
