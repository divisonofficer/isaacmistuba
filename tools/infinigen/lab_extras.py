"""N2 lab extras (floor N2 review r20, refs_answer gaps). Hooked from kit_lighting after lab_ceiling; every part is its own env flag and idempotent (kit passes run in place):

  ROOM_LAB_FLOORMARKS=1   yellow floor-tape corner brackets round every gas rack / cylinder cart / chamber / instrument rack / optical table (0.12 m off the footprint, 5 cm tape), and a mottled
                          epoxy floor: large soft stains in the colour and a patchy roughness on every floor material that is not already mottled
  ROOM_LAB_BENCHDENSE=1   instruments on every Workbench: scopes, stacked power supplies, optical stands (plate, posts, lens tube, mirror mounts), a multimeter, beakers and reagent bottles, loose cables
                          on the top, bins / boxes / bottles on the shelf (parented to the bench)
  ROOM_LAB_PANEL_ROOMS=break-room   a white T-bar ceiling grid (0.6 m) with bright emissive panels and dark perimeter vent slots in these rooms (prefixes)
"""
from __future__ import annotations

import math
import os
import random

import bmesh
import bpy
from mathutils import Vector

import room_dressing as rd
from room_planner import proc_assets as pa
from room_planner import proc_boutique_flagship as fl

BAY = ("GasCylinderRack", "GasCylinderCart", "VacuumChamber", "LabChamber", "InstrumentRack", "OpticalTable")


def _bb(o):
    pts = [o.matrix_world @ Vector(c) for c in o.bound_box]
    return min(p.x for p in pts), max(p.x for p in pts), min(p.y for p in pts), max(p.y for p in pts), min(p.z for p in pts), max(p.z for p in pts)


def _drop(prefix):
    for o in [o for o in bpy.data.objects if o.name.startswith(prefix)]:
        bpy.data.objects.remove(o, do_unlink=True)


def _emit(name, rgb, strength):
    m = fl._flat(name, rgb, 0.4); b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Emission Color"].default_value = (*rgb, 1.0); b.inputs["Emission Strength"].default_value = strength
    return m


# ---------------------------------------------------------------- floor
def _mottle(mat):
    if mat is None or not mat.use_nodes or mat.get("ir_mottle"):
        return 0
    nt = mat.node_tree; N, Lk = nt.nodes, nt.links
    b = next((n for n in N if n.type == "BSDF_PRINCIPLED"), None)
    if b is None:
        return 0
    geo = N.new("ShaderNodeNewGeometry")
    n1 = N.new("ShaderNodeTexNoise"); n1.inputs["Scale"].default_value = 0.9; n1.inputs["Detail"].default_value = 6.0; n1.inputs["Roughness"].default_value = 0.6; n1.inputs["Distortion"].default_value = 0.8
    n2 = N.new("ShaderNodeTexNoise"); n2.inputs["Scale"].default_value = 3.2; n2.inputs["Detail"].default_value = 4.0
    Lk.new(geo.outputs["Position"], n1.inputs["Vector"]); Lk.new(geo.outputs["Position"], n2.inputs["Vector"])
    ramp = N.new("ShaderNodeValToRGB"); ramp.color_ramp.elements[0].position = 0.35; ramp.color_ramp.elements[0].color = (0.62, 0.6, 0.55, 1); ramp.color_ramp.elements[1].position = 0.62; ramp.color_ramp.elements[1].color = (1, 1, 1, 1)
    Lk.new(n1.outputs["Fac"], ramp.inputs["Fac"])
    mx = N.new("ShaderNodeMixRGB"); mx.blend_type = "MULTIPLY"; mx.inputs["Fac"].default_value = 1.0
    src = b.inputs["Base Color"].links[0].from_socket if b.inputs["Base Color"].links else None
    if src is not None:
        Lk.new(src, mx.inputs["Color1"])
    else:
        mx.inputs["Color1"].default_value = b.inputs["Base Color"].default_value
    Lk.new(ramp.outputs["Color"], mx.inputs["Color2"]); Lk.new(mx.outputs["Color"], b.inputs["Base Color"])
    r0 = b.inputs["Roughness"].default_value
    if not b.inputs["Roughness"].links:
        mr = N.new("ShaderNodeMapRange"); mr.inputs["To Min"].default_value = max(0.05, r0 * 0.7); mr.inputs["To Max"].default_value = r0 + 0.2
        Lk.new(n2.outputs["Fac"], mr.inputs["Value"]); Lk.new(mr.outputs["Result"], b.inputs["Roughness"])
    sc = N.new("ShaderNodeMapping"); sc.inputs["Scale"].default_value = (70.0, 1.6, 1.0); Lk.new(geo.outputs["Position"], sc.inputs["Vector"])          # faint long scratches (N2 r25: 'matte, no scratches')
    sn = N.new("ShaderNodeTexNoise"); sn.inputs["Scale"].default_value = 1.0; sn.inputs["Detail"].default_value = 2.0; Lk.new(sc.outputs["Vector"], sn.inputs["Vector"])
    sr = N.new("ShaderNodeMapRange"); sr.inputs["From Min"].default_value = 0.62; sr.inputs["From Max"].default_value = 0.7; Lk.new(sn.outputs["Fac"], sr.inputs["Value"])
    bp = N.new("ShaderNodeBump"); bp.inputs["Strength"].default_value = 0.12; bp.inputs["Distance"].default_value = 0.001; Lk.new(sr.outputs["Result"], bp.inputs["Height"])
    if b.inputs["Normal"].is_linked:
        Lk.new(b.inputs["Normal"].links[0].from_socket, bp.inputs["Normal"])
    Lk.new(bp.outputs["Normal"], b.inputs["Normal"])
    if "Coat Weight" in b.inputs and b.inputs["Coat Weight"].default_value < 0.5:
        b.inputs["Coat Weight"].default_value = 0.6; b.inputs["Coat Roughness"].default_value = 0.06                                           # a glossy epoxy
    mat["ir_mottle"] = True
    return 1


def floor_marks(stats):
    rooms = {n: p for n, p in rd._rooms().items() if "floor" in p}
    boxes = {n: _bb(p["floor"]) for n, p in rooms.items()}
    mm = 0
    for p in rooms.values():
        for sl in p["floor"].material_slots:
            mm += _mottle(sl.material)
    _drop("BayTape(")
    yel = fl._flat("ir_bay_tape", (0.92, 0.72, 0.04), 0.4)
    prims, n = [], 0
    for o in list(bpy.data.objects):
        if o.type != "MESH" or not o.name.startswith(BAY):
            continue
        x0, x1, y0, y1, z0, z1 = _bb(o)
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        room = next((b for b in boxes.values() if b[0] <= cx <= b[1] and b[2] <= cy <= b[3]), None)
        if room is None or z0 - room[5] > 0.15 or (x1 - x0) > 4.5 or (y1 - y0) > 4.5:
            continue
        zf = room[5] + 0.004
        m, w = 0.12, 0.05
        X0, X1, Y0, Y1 = x0 - m, x1 + m, y0 - m, y1 + m
        for (px, sx) in ((X0, 1), (X1, -1)):
            for (py, sy) in ((Y0, 1), (Y1, -1)):
                lx = min(0.5, (X1 - X0) * 0.35); ly = min(0.5, (Y1 - Y0) * 0.35)
                for (bx, by, sxs, sys_) in ((px + sx * lx / 2, py, lx, w), (px, py + sy * ly / 2, w, ly)):
                    if room[0] + 0.05 <= bx - sxs / 2 and bx + sxs / 2 <= room[1] - 0.05 and room[2] + 0.05 <= by - sys_ / 2 and by + sys_ / 2 <= room[3] - 0.05:
                        prims.append(("box", bx, by, zf, sxs, sys_, 0.008))
        n += 1
    if prims:
        fl.mesh_object("BayTape(all)", [(yel, prims)], bevel=False)
    stats["lab_floor"] = {"mottled_materials": mm, "bays": n, "tape_pieces": len(prims)}
    return n


# ---------------------------------------------------------------- benches
def _bench_parts(r, L, D, mats):
    top, shelf = {k: [] for k in mats}, {k: [] for k in mats}
    zt = 0.92

    def box(d, k, x, y, z, sx, sy, sz, yaw=0.0):
        d[k].append(("box", x, y, z, sx, sy, sz, yaw))

    def cyl(d, k, p0, p1, rad, seg=10):
        d[k].append(("cyl", p0, p1, rad, seg))
    ys = [(-L / 2 + 0.5) + i * ((L - 0.8) / 6) for i in range(7)]
    r.shuffle(ys)
    for y in ys[:6]:
        kind = r.choice(("scope", "psu", "optic", "optic", "meter", "glass", "scope", "psu"))
        x = r.uniform(-0.02, 0.1)
        if kind == "scope":
            box(top, "body", x, y, zt + 0.07, 0.32, 0.36, 0.14); sk = r.choice(("scr", "scr_a", "scr_b", "scr_w")); box(top, sk, x + 0.161, y - 0.05, zt + 0.085, 0.004, 0.16, 0.09)
            for q in range(r.randint(2, 4)):                              # BNC ports along the bottom edge
                cyl(top, "alu", (x + 0.16, y - 0.12 + q * 0.05, zt + 0.025), (x + 0.178, y - 0.12 + q * 0.05, zt + 0.025), 0.009)
            box(top, "wht", x + 0.161, y + 0.12, zt + 0.045, 0.003, 0.07, 0.02)       # a label strip
            for k in range(4):
                cyl(top, "alu", (x + 0.16, y + 0.06 + 0.035 * (k % 2) * 0 + 0.0, zt + 0.1 - 0.035 * (k // 2)), (x + 0.185, y + 0.06 + 0.05 * (k % 2), zt + 0.1 - 0.035 * (k // 2)), 0.013)
            box(top, "led", x + 0.162, y + 0.15, zt + 0.12, 0.004, 0.012, 0.012)
        elif kind == "psu":
            for s in range(r.choice((2, 3))):
                box(top, "body", x, y, zt + 0.045 + s * 0.095, 0.3, 0.3, 0.09); box(top, r.choice(("scr", "scr_a", "scr_b", "scr_w")), x + 0.151, y - 0.07, zt + 0.045 + s * 0.095, 0.004, 0.1, 0.035); box(top, "wht", x + 0.151, y + 0.02, zt + 0.07 + s * 0.095, 0.003, 0.06, 0.012)
                cyl(top, "red", (x + 0.15, y + 0.09, zt + 0.03 + s * 0.095), (x + 0.17, y + 0.09, zt + 0.03 + s * 0.095), 0.01); cyl(top, "alu", (x + 0.15, y + 0.12, zt + 0.03 + s * 0.095), (x + 0.17, y + 0.12, zt + 0.03 + s * 0.095), 0.01)
        elif kind == "optic":
            box(top, "alu", x, y, zt + 0.01, 0.26, 0.26, 0.02)
            for (px, py) in ((-0.08, -0.08), (0.08, 0.08), (0.0, -0.09)):
                cyl(top, "alu", (x + px, y + py, zt + 0.02), (x + px, y + py, zt + 0.2 + r.uniform(0, 0.08)), 0.006)
            cyl(top, "blk", (x - 0.1, y, zt + 0.1), (x + 0.1, y, zt + 0.1), 0.026, 14); cyl(top, "alu", (x + 0.1, y, zt + 0.1), (x + 0.11, y, zt + 0.1), 0.03, 14)
            cyl(top, "alu", (x + 0.08, y + 0.08, zt + 0.19), (x + 0.088, y + 0.08, zt + 0.19), 0.025, 14)
        elif kind == "meter":
            box(top, "yel", x, y, zt + 0.02, 0.09, 0.18, 0.04, r.uniform(-0.4, 0.4)); box(top, "scr", x + 0.046, y, zt + 0.03, 0.003, 0.08, 0.035)
        else:
            for q in range(r.randint(2, 4)):
                yy = y + q * 0.11 - 0.15
                cyl(top, "glass", (x, yy, zt), (x, yy, zt + r.uniform(0.1, 0.2)), r.uniform(0.03, 0.05), 14)
    for q in range(3):                                                  # loose cables across the top
        y0 = r.uniform(-L / 2 + 0.5, L / 2 - 0.3); x0 = r.uniform(-0.15, 0.2); pts = [(x0, y0)]
        for s in range(r.randint(3, 5)):
            pts.append((pts[-1][0] + r.uniform(-0.12, 0.12), pts[-1][1] + r.uniform(-0.25, 0.25)))
        k = r.choice(("blk", "red", "blue"))
        for a, b in zip(pts, pts[1:]):
            cyl(top, k, (a[0], a[1], zt + 0.006), (b[0], b[1], zt + 0.006), 0.004, 6)
    zs = 0.9 + 0.42 + 0.02                                              # shelf top
    xs = -D / 2 + 0.15
    for i in range(r.randint(6, 9)):
        y = -L / 2 + 0.2 + i * ((L - 0.4) / 8) + r.uniform(-0.05, 0.05)
        c = r.choice(("bin", "box", "bottle", "bottle", "inst"))
        if c == "bin":
            box(shelf, "blue", xs, y, zs + 0.06, 0.22, 0.28, 0.12)
        elif c == "box":
            box(shelf, "card", xs, y, zs + 0.08, 0.2, 0.24, 0.16, r.uniform(-0.3, 0.3))
        elif c == "bottle":
            h = r.uniform(0.16, 0.26); cyl(shelf, "wht", (xs, y, zs), (xs, y, zs + h), 0.04, 12); cyl(shelf, "blue", (xs, y, zs + h), (xs, y, zs + h + 0.03), 0.025, 10)
        else:
            box(shelf, "body", xs + 0.02, y, zs + 0.07, 0.22, 0.26, 0.14); box(shelf, "scr", xs + 0.131, y, zs + 0.08, 0.004, 0.14, 0.07)
    return top, shelf


def bench_dense(stats):
    _drop("LabBenchInstr(")
    mats = {"body": fl._flat("ir_lb_body", (0.16, 0.17, 0.18), 0.45, 0.4), "alu": fl._flat("ir_lb_alu", (0.75, 0.76, 0.78), 0.3, 1.0), "blk": fl._flat("ir_lb_blk", (0.03, 0.03, 0.035), 0.5),
            "scr": _emit("ir_lb_scr", (0.15, 0.75, 0.55), 2.5), "scr_a": _emit("ir_lb_scr_a", (1.0, 0.55, 0.12), 2.2), "scr_b": _emit("ir_lb_scr_b", (0.15, 0.3, 1.0), 2.5), "scr_w": _emit("ir_lb_scr_w", (0.9, 0.95, 1.0), 2.0), "led": _emit("ir_lb_led", (0.2, 1.0, 0.3), 8.0), "red": fl._flat("ir_lb_red", (0.75, 0.08, 0.06), 0.4),
            "blue": fl._flat("ir_lb_blue", (0.1, 0.25, 0.6), 0.45), "yel": fl._flat("ir_lb_yel", (0.9, 0.7, 0.05), 0.45), "wht": fl._flat("ir_lb_wht", (0.88, 0.88, 0.86), 0.4),
            "card": fl._flat("ir_lb_card", (0.55, 0.42, 0.28), 0.8), "glass": pa._flat("ir_lb_glass", (0.85, 0.9, 0.92), 0.05, transmission=0.6)}
    n = 0
    for b in [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith("WorkbenchFactory") and o.parent is None]:
        r = random.Random(b.name)
        L, D = max(b.dimensions.y / abs(b.scale.y or 1.0), 1.0), b.dimensions.x / abs(b.scale.x or 1.0)      # local (unscaled) size: the instruments are parented, so they scale with the bench
        top, shelf = _bench_parts(r, L, D, mats)
        merged = {}
        for d in (top, shelf):
            for k, v in d.items():
                merged.setdefault(k, []).extend(v)
        o = fl.mesh_object(f"LabBenchInstr({b.name})", [(mats[k], v) for k, v in merged.items() if v], bevel=False)
        o.parent = b                                                    # identity parent inverse: the mesh is in the bench's local frame
        n += 1
    stats["lab_bench_dense"] = n
    return n


# ---------------------------------------------------------------- panel ceiling
def panel_ceiling(stats):
    pref = tuple(x for x in os.environ.get("ROOM_LAB_PANEL_ROOMS", "").split(",") if x)
    if not pref:
        return 0
    _drop("LabPanelCeiling(")
    done = 0
    bar = fl._flat("ir_pc_bar", (0.86, 0.86, 0.85), 0.5); vent = fl._flat("ir_pc_vent", (0.03, 0.03, 0.03), 0.6); pan = _emit("ir_pc_panel", (1.0, 0.97, 0.9), 7.0)
    for name, p in rd._rooms().items():
        if "floor" not in p or "wall" not in p or not name.startswith(pref):
            continue
        x0, x1, y0, y1, _a, _b = _bb(p["floor"]); zc = _bb(p["wall"])[5]
        taken = [(o.matrix_world.translation.x, o.matrix_world.translation.y) for o in bpy.data.objects
                 if o.type in ("MESH", "LIGHT") and o.matrix_world.translation.z > zc - 0.6 and x0 < o.matrix_world.translation.x < x1 and y0 < o.matrix_world.translation.y < y1
                 and any(k in o.name for k in ("CeilingLight", "AboCeilingFixture", "Sprinkler", "AcCassette", "TrackSpot", "TrackRail"))]
        g = 0.6; nx, ny = int((x1 - x0 - 0.4) // g), int((y1 - y0 - 0.4) // g)
        ox, oy = x0 + ((x1 - x0) - nx * g) / 2, y0 + ((y1 - y0) - ny * g) / 2
        bars, pans, vents = [], [], []
        zz = zc - 0.006
        for i in range(nx + 1):
            bars.append(("box", ox + i * g, (oy + oy + ny * g) / 2, zz, 0.025, ny * g, 0.012))
        for j in range(ny + 1):
            bars.append(("box", (ox + ox + nx * g) / 2, oy + j * g, zz, nx * g, 0.025, 0.012))
        lights = []
        for i in range(nx):
            for j in range(ny):
                cx, cy = ox + (i + 0.5) * g, oy + (j + 0.5) * g
                if (i + 2 * j) % 4 == 0 and not any(abs(cx - tx) < 0.5 and abs(cy - ty) < 0.5 for tx, ty in taken):
                    pans.append(("box", cx, cy, zc - 0.012, g - 0.04, g - 0.04, 0.008)); lights.append((cx, cy))
        for k in range(int((x1 - x0 - 1.0) // 1.5)):                    # dark vent slots along the two long walls
            vx = x0 + 0.8 + k * 1.5
            for vy in (y0 + 0.18, y1 - 0.18):
                vents.append(("box", vx, vy, zc - 0.008, 0.9, 0.05, 0.01))
        fl.mesh_object(f"LabPanelCeiling({name})", [(bar, bars), (pan, pans), (vent, vents)], bevel=False)
        for q, (cx, cy) in enumerate(lights[::3][:10]):
            ld = bpy.data.lights.new(f"ir_pc_{name}_{q}", "AREA"); ld.shape = "SQUARE"; ld.size = 0.6; ld.energy = 60.0; ld.color = (1.0, 0.96, 0.88)
            lo = bpy.data.objects.new(f"LabPanelCeiling(light {name} {q})", ld); bpy.context.scene.collection.objects.link(lo); lo.location = (cx, cy, zc - 0.03); lo.rotation_euler = (math.pi, 0, 0)
        done += 1
    stats["lab_panel_ceiling"] = done
    return done


def mirror_clear(stats):
    """ROOM_MIRROR_CLEAR=1 (N2 r23 LAY-02: a leaning mirror overlapped wall-hung panels in closet_0/0): any wall-hung panel / sign / picture / display whose world box overlaps a mirror's box (+3 cm) is removed; the mirror stays."""
    others = ("NoticePanel", "DoorSafetySign", "ClinicWallItem", "WallArt", "WallDisplay", "LabHangingSign")
    mirrors = [o for o in bpy.data.objects if o.type == "MESH" and o.parent is None and o.name.split("(")[0].startswith("Mirror")]
    n = 0
    for m in mirrors:
        mb = [m.matrix_world @ Vector(c) for c in m.bound_box]; m0 = [min(q[i] for q in mb) - 0.03 for i in range(3)]; m1 = [max(q[i] for q in mb) + 0.03 for i in range(3)]
        for o in [o for o in bpy.data.objects if o.type == "MESH" and o.parent is None and o.name.split("(")[0].startswith(others)]:
            ob = [o.matrix_world @ Vector(c) for c in o.bound_box]
            if all(min(q[i] for q in ob) < m1[i] and max(q[i] for q in ob) > m0[i] for i in range(3)):
                bpy.data.objects.remove(o, do_unlink=True); n += 1
    stats["mirror_clear"] = n
    return n


def optical_tables(stats):
    """ROOM_LAB_OPTICS=1 (N2 r25: 'the optical-table tops read as grooved planks'): the table steel (ir_ot_steel) becomes a flat brushed stainless: roughness 0.25-0.38 with a fine anisotropic streak, anisotropy 0.5, and a 25 mm
    tapped-hole grid (3 mm holes, darker inside) as a bump + albedo mask, in the table's object coordinates. Only Principled inputs are driven (albedo / roughness / normal GT)."""
    m = bpy.data.materials.get("ir_ot_steel")
    if m is None or not m.use_nodes or m.get("ir_ot_done"):
        return 0
    nt = m.node_tree; N, L = nt.nodes, nt.links
    for nd in list(N):
        if nd.type not in ("OUTPUT_MATERIAL",):
            N.remove(nd)
    out = next(n for n in N if n.type == "OUTPUT_MATERIAL")
    b = N.new("ShaderNodeBsdfPrincipled"); L.new(b.outputs["BSDF"], out.inputs["Surface"])
    b.inputs["Metallic"].default_value = 1.0
    if "Anisotropic" in b.inputs:
        b.inputs["Anisotropic"].default_value = 0.5
    tc = N.new("ShaderNodeTexCoord")
    mg = N.new("ShaderNodeMapping"); mg.inputs["Scale"].default_value = (40.0, 40.0, 40.0); L.new(tc.outputs["Object"], mg.inputs["Vector"])          # 25 mm cells
    sp = N.new("ShaderNodeSeparateXYZ"); L.new(mg.outputs["Vector"], sp.inputs[0])
    def fr(sock):
        f = N.new("ShaderNodeMath"); f.operation = "FRACT"; L.new(sock, f.inputs[0]); s2 = N.new("ShaderNodeMath"); s2.operation = "SUBTRACT"; s2.inputs[1].default_value = 0.5; L.new(f.outputs[0], s2.inputs[0]); return s2.outputs[0]
    cb = N.new("ShaderNodeCombineXYZ"); L.new(fr(sp.outputs["X"]), cb.inputs["X"]); L.new(fr(sp.outputs["Y"]), cb.inputs["Y"])
    ln = N.new("ShaderNodeVectorMath"); ln.operation = "LENGTH"; L.new(cb.outputs[0], ln.inputs[0])
    mk = N.new("ShaderNodeMapRange"); mk.inputs["From Min"].default_value = 0.10; mk.inputs["From Max"].default_value = 0.14; L.new(ln.outputs["Value"], mk.inputs["Value"])             # 0 inside the hole, 1 on the plate
    st = N.new("ShaderNodeMath"); st.operation = "MULTIPLY"; st.use_clamp = True; st.inputs[1].default_value = 1.0
    mg2 = N.new("ShaderNodeMapping"); mg2.inputs["Scale"].default_value = (350.0, 6.0, 6.0); L.new(tc.outputs["Object"], mg2.inputs["Vector"])                 # streaks along the table's x
    nz = N.new("ShaderNodeTexNoise"); nz.inputs["Scale"].default_value = 1.0; nz.inputs["Detail"].default_value = 3.0; L.new(mg2.outputs["Vector"], nz.inputs["Vector"])
    rg = N.new("ShaderNodeMapRange"); rg.inputs["To Min"].default_value = 0.25; rg.inputs["To Max"].default_value = 0.38; L.new(nz.outputs["Fac"], rg.inputs["Value"]); L.new(rg.outputs["Result"], b.inputs["Roughness"])
    col = N.new("ShaderNodeMix"); col.data_type = "RGBA"; col.blend_type = "MULTIPLY"; col.inputs[6].default_value = (0.72, 0.73, 0.75, 1); L.new(mk.outputs["Result"], col.inputs["Factor"]); col.inputs[7].default_value = (0.25, 0.25, 0.27, 1)
    inv = N.new("ShaderNodeMix"); inv.data_type = "RGBA"; inv.inputs[6].default_value = (0.2, 0.2, 0.22, 1); inv.inputs[7].default_value = (0.72, 0.73, 0.75, 1); L.new(mk.outputs["Result"], inv.inputs["Factor"]); L.new(inv.outputs[2], b.inputs["Base Color"])
    bp2 = N.new("ShaderNodeBump"); bp2.inputs["Strength"].default_value = 0.6; bp2.inputs["Distance"].default_value = 0.0015; L.new(nz.outputs["Fac"], bp2.inputs["Height"])
    bp = N.new("ShaderNodeBump"); bp.inputs["Strength"].default_value = 1.0; bp.inputs["Distance"].default_value = 0.002; L.new(mk.outputs["Result"], bp.inputs["Height"]); L.new(bp2.outputs["Normal"], bp.inputs["Normal"]); L.new(bp.outputs["Normal"], b.inputs["Normal"])
    m["ir_ot_done"] = True; m["weathered"] = True; b["weathered"] = True
    stats["optical_tables"] = 1
    return 1


def wall_dedupe(stats):
    """ROOM_WALL_DEDUPE=1 (O4 r8 LAY-02: two large whiteboards from the neighbouring rooms cross through each other on the shared glass partition): of any two wall-hung items (whiteboards, pictures, displays, notice / pin / felt panels,
    clinic wall items, mirrors) whose world boxes overlap (+2 cm), the smaller is removed. Kit stage; the walls' own geometry is untouched."""
    KEYS = ("Whiteboard", "WallArt", "WallDisplay", "NoticePanel", "PinBoard", "Pinboard", "FeltPanel", "ClinicWallItem", "Mirror", "WallPanel", "DoorSafetySign")
    items = [o for o in bpy.data.objects if o.type == "MESH" and o.parent is None and o.name.split("(")[0].startswith(KEYS)]
    box = {}
    for o in items:
        q = [o.matrix_world @ Vector(c) for c in o.bound_box]; box[o.name] = [(min(v[i] for v in q) - 0.02, max(v[i] for v in q) + 0.02) for i in range(3)]
    vol = lambda b: (b[0][1] - b[0][0]) * (b[1][1] - b[1][0]) * (b[2][1] - b[2][0])
    gone, n = set(), 0
    names = sorted(box, key=lambda k: -vol(box[k]))
    for i, a in enumerate(names):
        if a in gone:
            continue
        for b in names[i + 1:]:
            if b in gone:
                continue
            if all(box[a][k][0] < box[b][k][1] and box[b][k][0] < box[a][k][1] for k in range(3)):
                gone.add(b)
    for nm in gone:
        o = bpy.data.objects.get(nm)
        if o is not None:
            bpy.data.objects.remove(o, do_unlink=True); n += 1
    stats["wall_dedupe"] = n
    return n


def apply(stats):
    if os.environ.get("ROOM_WALL_DEDUPE") == "1":
        wall_dedupe(stats)
    if os.environ.get("ROOM_LAB_OPTICS") == "1":
        optical_tables(stats)
    if os.environ.get("ROOM_MIRROR_CLEAR") == "1":
        mirror_clear(stats)
    if os.environ.get("ROOM_LAB_FLOORMARKS") == "1":
        floor_marks(stats)
    if os.environ.get("ROOM_LAB_BENCHDENSE") == "1":
        bench_dense(stats)
    panel_ceiling(stats)
