"""Floor-to-ceiling glass partitions between rooms (floor O review: continuous glass walls with thin stainless-steel frames and a frosted band at 1.0-1.5 m separate the corridor from the
offices / meeting rooms; the doors are glass with long stainless pull handles; green EXIT signs hang in the corridor). Env: ROOM_GLASS_PARTITIONS=hallway,meeting-room (room types); ROOM_GLASS_NEIGHBOURS=balcony (only neighbours with these name prefixes); ROOM_GLASS_SERVICE_OK=utility (glaze these service-room neighbours too, normally skipped); with ROOM_TERRACE_OPEN=1 a balcony neighbour is glazed (clear, no frost).

Two hooks:
  apply(room_name, zc, stats)   architecture_pass, once per room (like big_glass.apply): for a room of a listed type, every neighbouring room that shares a wall line with it (floor boxes
                                 within 0.45 m, overlap >= 1.0 m) gets that stretch (less 8 cm at the corners) carved out of BOTH rooms' `.wall` meshes from the floor to 0.2 m under
                                 the ceiling (big_glass._carve), a head fascia added (big_glass._patch), and glass panes + stainless mullions / rails + a frosted band (z 1.0-1.5 m) built on the
                                 shared line. Segments are recorded in scene["ir_glass_parts"] for the second hook.
  finish(stats)                 kit_lighting (after flush_doors): door leaves standing in a recorded segment get a glass leaf (slab material -> glass; handles / kick plates stay) and a
                                 long stainless pull handle; hallway rooms get green double-sided EXIT signs hung from the ceiling every ~8 m.
Nothing is changed for rooms / neighbours not covered.
"""
from __future__ import annotations

import json
import math
import os

import bpy
from mathutils import Vector

from room_planner import big_glass as bg
from room_planner import proc_boutique_flagship as fl
from room_planner import rooftop_shell as rs

TYPES = tuple(t for t in os.environ.get("ROOM_GLASS_PARTITIONS", "").split(",") if t)


def _bbox(parts):
    f = parts["floor"]
    pts = [f.matrix_world @ Vector(c) for c in f.bound_box]
    return min(p.x for p in pts), max(p.x for p in pts), min(p.y for p in pts), max(p.y for p in pts), max(p.z for p in pts)


def _bb6(o):
    pts = [o.matrix_world @ Vector(c) for c in o.bound_box]
    return min(q.x for q in pts), max(q.x for q in pts), min(q.y for q in pts), max(q.y for q in pts), min(q.z for q in pts), max(q.z for q in pts)


def _frost():
    m = bpy.data.materials.get("ir_gp_frost")
    if m is None:
        m = bpy.data.materials.new("ir_gp_frost"); m.use_nodes = True
        nt = m.node_tree; N, L = nt.nodes, nt.links; N.clear()
        out = N.new("ShaderNodeOutputMaterial"); mx = N.new("ShaderNodeMixShader"); tr = N.new("ShaderNodeBsdfTransparent"); df = N.new("ShaderNodeBsdfPrincipled")
        df.inputs["Base Color"].default_value = (0.9, 0.92, 0.92, 1); df.inputs["Roughness"].default_value = 0.7; mx.inputs[0].default_value = 0.72
        lp = N.new("ShaderNodeLightPath"); ma = N.new("ShaderNodeMath"); ma.operation = "MULTIPLY_ADD"; ma.inputs[1].default_value = -0.57; ma.inputs[2].default_value = 0.72
        L.new(lp.outputs["Is Shadow Ray"], ma.inputs[0]); L.new(ma.outputs[0], mx.inputs[0])             # a shadow ray sees only 15 % of the frost: the 72 % diffuse cast soft dark smudges on the wall and floor behind the partition (J r47 AST-02)
        L.new(tr.outputs[0], mx.inputs[1]); L.new(df.outputs[0], mx.inputs[2]); L.new(mx.outputs[0], out.inputs["Surface"])
    return m


def _steel():
    return fl._flat("ir_gp_steel", (0.62, 0.63, 0.65), 0.28, 1.0)


def apply(room_name, zc, stats):
    if not TYPES or room_name.split("_")[0] not in TYPES:
        return 0
    import room_dressing as rd
    rooms = rd._rooms()
    me = rooms.get(room_name)
    if me is None or "floor" not in me:
        return 0
    bx0, bx1, by0, by1, fz = _bbox(me)
    done = []
    for oname, parts in rooms.items():
        if oname == room_name or "floor" not in parts or (oname.split("_")[0] in ("balcony", "closet", "utility", "restroom", "bathroom", "kitchen") and not (oname.startswith("balcony") and os.environ.get("ROOM_TERRACE_OPEN") == "1")
                                                     and oname.split("_")[0] not in os.environ.get("ROOM_GLASS_SERVICE_OK", "").split(",")):   # e.g. utility: O2's atrium is a utility room seen from the corridor through glass (user 10-23)
            continue
        only_ = tuple(x for x in os.environ.get("ROOM_GLASS_NEIGHBOURS", "").split(",") if x)      # e.g. balcony: glaze only the neighbours with these name prefixes (the dining room's wall to the terrace, not its open edge to the living room)
        if only_ and not oname.startswith(only_):
            continue
        if oname.split("_")[0] in TYPES and oname < room_name:                    # a pair between two listed rooms is built once
            continue
        nx0, nx1, ny0, ny1, _ = _bbox(parts)
        segs = []
        for axis in ("x", "y"):                                                     # shared wall line perpendicular to this axis
            a0, a1, b0, b1 = (bx0, bx1, nx0, nx1) if axis == "x" else (by0, by1, ny0, ny1)
            lo_o, hi_o = (max(by0, ny0), min(by1, ny1)) if axis == "x" else (max(bx0, nx0), min(bx1, nx1))
            if hi_o - lo_o < 1.0:
                continue
            for ea, eb in ((a1, b0), (a0, b1)):
                if abs(ea - eb) < 0.45:
                    segs.append((axis, (ea, eb), lo_o, hi_o))
        for axis, (ea, eb), lo, hi in segs:
            ua, ub = lo + 0.08, hi - 0.08
            line = (ea + eb) / 2
            o0 = Vector((0.0, 0.0, 0.0)); ux = Vector((0, 1, 0)) if axis == "x" else Vector((1, 0, 0)); vx = Vector((1, 0, 0)) if axis == "x" else Vector((0, 1, 0))
            z1 = zc - 0.2
            removed = 0
            for nm, edge in ((f"{room_name}.wall", ea), (f"{oname}.wall", eb)):
                w = bpy.data.objects.get(nm)
                if w is None:
                    continue
                removed += bg._carve(w, o0, ux, vx, line, ua, ub, 0.02, z1, 0.45)
                ztop = max((w.matrix_world @ Vector(c)).z for c in w.bound_box)
                bg._patch(w, o0, ux, vx, edge, [(ua, ub, z1, ztop)])
            for nm in (f"{room_name}.exterior", f"{oname}.exterior"):         # the rooms' outer shell layer (no material: renders as a milky white sheet in the opening, P2b r4 'frosted' side panes)
                removed += bg._carve(bpy.data.objects.get(nm), o0, ux, vx, line, ua, ub, 0.02, z1 + 0.3, 0.7)
            if not removed:
                continue
            span = ub - ua; n = max(1, int(round(span / 1.5))); pitch = span / n
            P = lambda u, z, off=0.0: ((line + off, u, z) if axis == "x" else (u, line + off, z))
            sx, sy = (0.05, 0.04) if axis == "x" else (0.04, 0.05)
            steel = _steel(); pane = rs._glass("ir_gp_glass", rough=0.0)
            gaps = []                                                              # door openings in this line (O2 r5 AST-02: panes and rails ran straight across the door, 'broken glass edges')
            for dc in bpy.data.objects:
                if dc.type == "MESH" and dc.name.startswith("DoorCasingFactory"):
                    cb = _bb6(dc); cx_, cy_ = (cb[0] + cb[1]) / 2, (cb[2] + cb[3]) / 2
                    if (axis == "x" and abs(cx_ - line) < 0.4 and ua - 0.3 < cy_ < ub + 0.3) or (axis == "y" and abs(cy_ - line) < 0.4 and ua - 0.3 < cx_ < ub + 0.3):
                        c_ = cy_ if axis == "x" else cx_; hw_ = ((cb[3] - cb[2]) if axis == "x" else (cb[1] - cb[0])) / 2 + 0.03
                        gaps.append((c_ - hw_, c_ + hw_, cb[5]))
            gaps.sort()

            def segs_(u0, u1, minw=0.08):                                          # [u0, u1] minus the door gaps
                out_, cur = [], u0
                for g0, g1, _zt in gaps:
                    if g1 <= cur or g0 >= u1:
                        continue
                    if g0 - cur >= minw:
                        out_.append((cur, g0))
                    cur = max(cur, g1)
                if u1 - cur >= minw:
                    out_.append((cur, u1))
                return out_
            posts = [("box", *P(ua + k * pitch, fz + (z1 - fz) / 2)[:2], fz + (z1 - fz) / 2, sx, sy, z1 - fz) for k in range(n + 1)]
            terr = oname.startswith("balcony")                                   # a terrace sliding wall (ROOM_TERRACE_OPEN=1): clear glass, no frosted band, no mid rails
            posts = [q for q in posts if True]
            rails = [(fz + 0.04, 0.08), (z1 - 0.03, 0.06)] + ([] if terr else [(fz + 1.0, 0.035), (fz + 1.5, 0.035)])
            for ra, rb in segs_(ua, ub, 0.05):
                sd = (0.045, rb - ra) if axis == "x" else (rb - ra, 0.045)
                for zr, th in rails:
                    posts.append(("box", *P((ra + rb) / 2, zr)[:2], zr, *sd, th))
            posts = [q for q in posts if not any(g0 < (q[2] if axis == "x" else q[1]) < g1 and q[6] > 1.0 for g0, g1, _zt in gaps)]   # no post inside a door opening
            for g0, g1, _zt in gaps:                                                  # door jamb posts at the opening edges
                for uj in (g0, g1):
                    if ua < uj < ub:
                        posts.append(("box", *P(uj, fz + (z1 - fz) / 2)[:2], fz + (z1 - fz) / 2, sx, sy, z1 - fz))
            fl.mesh_object(f"GlassPartitionFrame({room_name}|{oname}|{axis}{len(done)})", [(steel, posts)], bevel=False)
            quad = lambda u0, u1, za, zb: ((*P(u0, za),), (*P(u1, za),), (*P(u1, zb),), (*P(u0, zb),))
            pq = []
            for k in range(n):
                for sa, sb in segs_(ua + k * pitch + 0.025, ua + (k + 1) * pitch - 0.025, 0.12):
                    pq.append(quad(sa, sb, fz + 0.09, z1 - 0.06))
            for g0, g1, zt_ in gaps:                                              # a fixed pane + rail over each door (the head)
                if ua < g1 and g0 < ub and z1 - 0.06 - zt_ > 0.12:
                    pq.append(quad(max(g0, ua), min(g1, ub), zt_ + 0.05, z1 - 0.06))
                    sd = (0.045, min(g1, ub) - max(g0, ua)) if axis == "x" else (min(g1, ub) - max(g0, ua), 0.045)
                    posts_head = ("box", *P((max(g0, ua) + min(g1, ub)) / 2, zt_ + 0.025)[:2], zt_ + 0.025, *sd, 0.05)
                    fl.mesh_object(f"GlassPartitionHead({room_name}|{oname}|{len(done)})", [(steel, [posts_head])], bevel=False)
            rs._quads(f"GlassPartitionPanes({room_name}|{oname}|{len(done)})", pq, pane, thick=rs.GLASS_THICK)
            if not terr:
                if os.environ.get("ROOM_GLASS_FROST") == "stripes":                       # O2 hallway ref: vertical frosted STRIPES (0.12 m every 0.3 m) instead of one horizontal band
                    st_ = []
                    for k in range(n):
                        u0 = ua + k * pitch + 0.1
                        while u0 + 0.12 < ua + (k + 1) * pitch - 0.08:
                            st_.extend(quad(sa, sb, fz + 0.5, z1 - 0.5) for sa, sb in segs_(u0, u0 + 0.12, 0.1)); u0 += 0.3
                    rs._quads(f"GlassPartitionFrost({room_name}|{oname}|{len(done)})", st_, _frost())
                else:
                    rs._quads(f"GlassPartitionFrost({room_name}|{oname}|{len(done)})", [quad(sa, sb, fz + 1.0, fz + 1.5) for k in range(n) for sa, sb in segs_(ua + k * pitch + 0.025, ua + (k + 1) * pitch - 0.025, 0.12)], _frost())
            done.append({"axis": axis, "line": line, "lo": ua, "hi": ub, "fz": fz, "z1": z1})
    if done:
        cur = json.loads(bpy.context.scene.get("ir_glass_parts", "[]")) + done
        bpy.context.scene["ir_glass_parts"] = json.dumps(cur)
        stats["glass_partitions"] = stats.get("glass_partitions", 0) + len(done)
    return len(done)


def finish(stats):
    """Glass door leaves + pull handles in the recorded segments, EXIT signs in the hallways."""
    segs = json.loads(bpy.context.scene.get("ir_glass_parts", "[]"))
    if not segs and "hallway" not in TYPES:
        return 0
    glass = rs._glass("ir_gp_leaf_glass", rough=0.0); steel = _steel(); n_doors = 0
    for o in list(bpy.data.objects):
        if o.type != "MESH" or not o.name.startswith("LiteDoorFactory") or not o.data.name.startswith("ir_flush_leaf"):
            continue
        t = o.parent.matrix_world.translation if o.parent is not None else o.matrix_world.translation
        for s in segs:
            c, u = ((t.x, t.y) if s["axis"] == "x" else (t.y, t.x))
            if abs(c - s["line"]) < 0.7 and s["lo"] - 0.3 < u < s["hi"] + 0.3:
                for slot in o.material_slots:
                    if slot.material is not None and slot.material.name.startswith("ir_office_door_leaf"):
                        slot.material = glass
                n_doors += 1
                break
    # green EXIT signs over the hallway
    n_sign = 0
    import room_dressing as rd
    hall_ok = "hallway" in TYPES
    if hall_ok:
        green = fl._flat("ir_gp_exit_green", (0.1, 0.8, 0.3), 0.4); hous = fl._flat("ir_gp_exit_housing", (0.05, 0.05, 0.055), 0.5)
        bs = green.node_tree.nodes["Principled BSDF"]; bs.inputs["Emission Color"].default_value = (0.1, 0.9, 0.35, 1); bs.inputs["Emission Strength"].default_value = 8.0
        for name, parts in rd._rooms().items():
            if name.split("_")[0] != "hallway" or "floor" not in parts:
                continue
            x0, x1, y0, y1, fz = _bbox(parts); alx = (x1 - x0) >= (y1 - y0)
            L = (x1 - x0) if alx else (y1 - y0)
            lab = os.environ.get("ROOM_LAB_SIGNS") == "1"           # N2 r7: the refs hang red-lettered Korean warning boards, not blank glowing green rectangles
            step = 5.0 if lab else 8.0
            us_ = [(k + 0.5) * L / max(1, int(L // step)) for k in range(max(1, int(L // step)))]
            if os.environ.get("ROOM_EXIT_SIGN_ENDS") == "1":         # O2 r14 CNT-02: one board at each end of a corridor (the stair / exit doors), not a row of identical ones
                us_ = [0.8, L - 0.8] if L > 3.0 else [L / 2]
            for k, u in enumerate(us_):
                cx, cy = ((x0 + u, (y0 + y1) / 2) if alx else ((x0 + x1) / 2, y0 + u)); z = fz + 2.2
                if lab:
                    import glob
                    from room_planner import proc_assets as pa_
                    imgs = sorted(glob.glob("/jarvis/project/robomituba/data/venue_refs/prop_textures/" + ("safety_sign_03.png" if os.environ.get("ROOM_LAB_SIGNS_SET") == "exit" else "lab_sign_ko_*.png")))   # ROOM_LAB_SIGNS_SET=exit: green EXIT pictogram boards (offices)
                    if imgs:
                        from pathlib import Path
                        pm = pa_._printed(Path(imgs[(k + int(x0 * 3 + y0 * 7)) % len(imgs)]), (0.95, 0.95, 0.93), 0.55)
                        zc = fz + 2.28; bw, bh = ((0.44, 0.44) if os.environ.get("ROOM_LAB_SIGNS_SET") == "exit" else (0.62, 0.465))                       # a 4:3 board hung on two rods, double sided, turned across the corridor
                        sx, sy = ((0.03, bw) if alx else (bw, 0.03)); px, py = ((0.017, 0.0) if alx else (0.0, 0.017)); ps = ((0.003, bw - 0.02) if alx else (bw - 0.02, 0.003))
                        rods = [("box", cx, cy + o_ * (bw / 2 - 0.05) * (1 if alx else 0), zc + bh / 2 + 0.095, 0.01, 0.01, 0.19) if alx else ("box", cx + o_ * (bw / 2 - 0.05), cy, zc + bh / 2 + 0.095, 0.01, 0.01, 0.19) for o_ in (1, -1)]
                        fl.mesh_object(f"LabHangingSign({name}|{k})", [(hous, [("box", cx, cy, zc, sx, sy, bh)] + rods),
                                                                     (pm, [("box", cx + px, cy + py, zc, *((ps[0], ps[1], bh - 0.02) if alx else (ps[0], ps[1], bh - 0.02))), ("box", cx - px, cy - py, zc, *((ps[0], ps[1], bh - 0.02) if alx else (ps[0], ps[1], bh - 0.02)))])], bevel=False)
                        n_sign += 1
                        continue
                sz = (0.05, 0.5, 0.2) if alx else (0.5, 0.05, 0.2)
                gs = (0.012, 0.44, 0.15) if alx else (0.44, 0.012, 0.15)
                dgs = (0.05, 0.0) if alx else (0.0, 0.05)
                parts_ = [("box", cx, cy, z, *sz)]
                fl.mesh_object(f"GlassExitSign({name}|{k})", [(hous, parts_), (green, [("box", cx + dgs[0], cy + dgs[1], z, *gs), ("box", cx - dgs[0], cy - dgs[1], z, *gs)])], bevel=False)
                n_sign += 1
    n_strip = 0
    if hall_ok and os.environ.get("ROOM_HALL_CEILING_STRIPS") == "1":                       # O2 hallway ref: metal ceiling strips (longitudinal steel battens, one every 0.45 m across the corridor)
        for name, parts in rd._rooms().items():
            if name.split("_")[0] != "hallway" or "floor" not in parts:
                continue
            x0, x1, y0, y1, fz = _bbox(parts); alx = (x1 - x0) >= (y1 - y0); w_ = (y1 - y0) if alx else (x1 - x0); L = (x1 - x0) if alx else (y1 - y0)
            wl = parts.get("wall"); zc_ = max(((wl.matrix_world @ Vector(c)).z for c in wl.bound_box), default=fz + 3.0) if wl is not None else fz + 3.0
            nb = max(2, int(w_ // 0.45)); bars = []
            for k in range(nb):
                v = (k + 0.5) * w_ / nb
                bars.append(("box", (x0 + x1) / 2 if alx else x0 + v, y0 + v if alx else (y0 + y1) / 2, zc_ - 0.015, *((L - 0.2, 0.05, 0.02) if alx else (0.05, L - 0.2, 0.02))))
            fl.mesh_object(f"HallCeilingStrips({name})", [(steel, bars)], bevel=False); n_strip += nb
    stats["glass_partitions_finish"] = {"glass_doors": n_doors, "exit_signs": n_sign, "ceiling_strips": n_strip}
    return n_doors + n_sign
