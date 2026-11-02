"""Ramen counter shop dressing (S32 user feedback 10-23: 'low and busy ceiling, no domestic round light', 'walls not empty'). Hooked from kit_lighting after the exposed ceiling, only when ROOM_RAMEN_DRESSING=1.

    from ramen_dressing import apply; stats["ramen_dressing"] = apply(stats)

Env: ROOM_RAMEN_DRESSING=1
     ROOM_RAMEN_LIGHTS=1   (default on) replace the domestic round ceiling fixtures (AboCeilingFixtureFactory) and their pendant point lights by two rows of small recessed downlights (counter side and staff aisle, every
                           0.9 m, warm 2700 K spots) and one cool (5000 K) area light under the hood, so the counter reads warm and the kitchen cool.
     ROOM_RAMEN_DECOR=1    (default on) menu boards, vertical paper menus, price tags, coat hooks, a small shelf and kitchen notices on the wall opposite the kitchen, spaced along it and clear of the door and window
Added for S32 r15 (user 10-23 'still a video game'), all inside ROOM_RAMEN_DRESSING=1:
     ROOM_RAMEN_CONTRAST=1 (default on)  R1: downlights become narrow 35 deg spots, 3-4 warm (2700 K) pendants hang low over the counter, every other fill light is scaled by ROOM_RAMEN_FILL (default 0.35) and the world
                           by ROOM_RAMEN_WORLD (default 0.3): bright counter, dark ceiling / back wall / under-counter.  ROOM_RAMEN_PENDANTS=4 sets their number.
     ROOM_RAMEN_WALL_TONE=0.7 / ROOM_RAMEN_CEILING_TONE=0.5  (R1b) base-colour multipliers for the wall / ceiling materials (warm).
     ROOM_RAMEN_COUNTER=1  (default on)  R2: the counter top gets a fine procedural grain (no stretched stripes), a dark edge band round the 40 mm slab, and the front panel a darker material (ROOM_RAMEN_COUNTER_FRONT=dark|black|steel).
     graphics              menu boards / paper menus / posters use data/venue_refs/ramen_shop_01/graphics/{menu_board_*,menu_strip_*,poster_*}.{png,jpg} when present, else the abstract bars.
Finds the room from the single ceiling object and the RamenKitchenFactory object (the kitchen side = the wall it stands against). Text is abstract (bars), no readable words or brands."""
from __future__ import annotations

import math
import os
import random

import bpy
from mathutils import Vector

from room_planner import proc_assets as pa
from room_planner import proc_boutique_flagship as fl


def _bb(o):
    pts = [o.matrix_world @ Vector(c) for c in o.bound_box]
    return min(p.x for p in pts), max(p.x for p in pts), min(p.y for p in pts), max(p.y for p in pts), min(p.z for p in pts), max(p.z for p in pts)


GRAPHICS = os.environ.get("ROOM_RAMEN_GRAPHICS") or "/jarvis/project/robomituba/data/venue_refs/ramen_shop_01/graphics"


def _gfx(prefix):
    import glob
    import re
    return sorted(f for ext in ("png", "jpg", "jpeg", "webp") for f in glob.glob(f"{GRAPHICS}/{prefix}*.{ext}") if re.match(rf"{re.escape(prefix)}_?\d+\.", os.path.basename(f)))      # menu_strip_01.png, not menu_strips_review.jpg


def _img_mat(path, rough=0.55):
    """A flat print material whose base colour is the image (cached per file)."""
    name = "ir_rd_gfx_" + os.path.basename(path)
    m = bpy.data.materials.get(name)
    if m is not None:
        return m
    m = bpy.data.materials.new(name); m.use_nodes = True
    nt = m.node_tree; b = nt.nodes["Principled BSDF"]
    tx = nt.nodes.new("ShaderNodeTexImage"); tx.image = bpy.data.images.load(path, check_existing=True); tx.image.colorspace_settings.name = "sRGB"; tx.extension = "EXTEND"
    nt.links.new(tx.outputs["Color"], b.inputs["Base Color"]); b.inputs["Roughness"].default_value = rough
    return m


def _decor(kind, r, gfx=None):
    """One wall piece in its own frame: back at x = 0, front +x, centred on y, z up from its bottom. -> (object, height)."""
    wood = pa._flat("ir_rd_wood", (0.38, 0.2, 0.08), 0.5, wood=True); card = pa._flat("ir_rd_card", (0.9, 0.86, 0.74), 0.6); ink = pa._flat("ir_rd_ink", (0.03, 0.025, 0.02), 0.6)
    red = pa._flat("ir_rd_red", (0.6, 0.04, 0.03), 0.5); white = pa._flat("ir_rd_paper", (0.93, 0.93, 0.9), 0.6); steel = pa._flat("ir_rd_steel", (0.7, 0.72, 0.74), 0.3, 1.0); blue = pa._flat("ir_rd_blue", (0.04, 0.1, 0.3), 0.6)
    R0 = (0, 0, 0); G = {"wood": [], "card": [], "ink": [], "red": [], "white": [], "steel": [], "blue": []}
    if kind == "board":                                                                       # a wooden menu board: frame, cream card, rows of abstract text bars, red price dots
        w, h = r.choice((0.5, 0.6)), r.choice((0.7, 0.9))
        if gfx:                                                                               # a generated menu-board picture: the frame fits the image's aspect, the card carries the print (no abstract bars)
            im = bpy.data.images.load(gfx[0], check_existing=True); asp = im.size[1] / max(im.size[0], 1)
            w = 0.55; h = min(max(w * asp, 0.45), 1.0)
            G["wood"] += [("box", (0.02, 0, h / 2), (0.04, w, h), R0)]; G["__img"] = [(gfx[0], [("box", (0.045, 0, h / 2), (0.01, w - 0.05, h - 0.05), R0)])]
            return G, h
        G["wood"] += [("box", (0.02, 0, h / 2), (0.04, w, h), R0)]; G["card"] += [("box", (0.045, 0, h / 2), (0.01, w - 0.06, h - 0.06), R0)]
        for k in range(int((h - 0.2) / 0.1)):
            ln = r.uniform(0.35, 0.8) * (w - 0.14)
            G["ink"] += [("box", (0.052, -(w - 0.14) / 2 + ln / 2, h - 0.1 - k * 0.1), (0.004, ln, 0.026), R0)]
            G["red"] += [("cyl", (0.052, (w - 0.14) / 2 - 0.03, h - 0.1 - k * 0.1), (0.016, 0.016, 0.004), (0, 1.5708, 0))]
        return G, h
    if kind == "papers":                                                                      # three vertical paper menus of different lengths, taped
        h = 0.6
        if gfx:                                                                               # generated menu strips: each paper carries one picture
            G["__img"] = []
            for k in range(3):
                hh = r.uniform(0.42, 0.6); y = (k - 1) * 0.17
                G["__img"].append((gfx[k % len(gfx)], [("box", (0.006, y, h - hh / 2), (0.004, 0.13, hh), R0)]))
            return G, h
        for k in range(3):
            hh = r.uniform(0.38, 0.6); y = (k - 1) * 0.17
            G["white"] += [("box", (0.006, y, h - hh / 2), (0.004, 0.13, hh), R0)]
            for q in range(int(hh / 0.07)):
                G["ink"] += [("box", (0.009, y, h - 0.05 - q * 0.065), (0.003, 0.09 * r.uniform(0.5, 1.0), 0.016), R0)]
            G["red"] += [("box", (0.009, y, h - hh + 0.03), (0.003, 0.13, 0.014), R0)]
        return G, h
    if kind == "poster" and gfx:                                                              # a framed poster from the generated graphics
        im = bpy.data.images.load(gfx[0], check_existing=True); asp = im.size[1] / max(im.size[0], 1)
        w = r.uniform(0.45, 0.6); h = min(max(w * asp, 0.4), 0.95)
        G["ink"] += [("box", (0.02, 0, h / 2), (0.03, w, h), R0)]; G["__img"] = [(gfx[0], [("box", (0.037, 0, h / 2), (0.006, w - 0.05, h - 0.05), R0)])]
        return G, h
    if kind == "tags":                                                                        # a row of small price tags on a wooden rail
        G["wood"] += [("box", (0.02, 0, 0.3), (0.03, 0.6, 0.03), R0)]
        for k in range(5):
            G["card"] += [("box", (0.03, -0.24 + k * 0.12, 0.2), (0.006, 0.09, 0.15), R0)]; G["ink"] += [("box", (0.034, -0.24 + k * 0.12, 0.21), (0.003, 0.06, 0.02), R0)]; G["red"] += [("box", (0.034, -0.24 + k * 0.12, 0.15), (0.003, 0.05, 0.03), R0)]
        return G, 0.4
    if kind == "hooks":                                                                       # a wooden rail with five hooks and a jacket-like cloth on one
        G["wood"] += [("box", (0.02, 0, 0.3), (0.04, 0.8, 0.07), R0)]
        for k in range(5):
            G["steel"] += [("cyl", (0.07, -0.32 + k * 0.16, 0.3), (0.012, 0.012, 0.06), (0, 1.5708, 0))]
        # (the blue jacket-like slab that hung on the rail was removed: it read as an abstract placeholder, S32 r19)
        return G, 0.6
    if kind == "shelf":                                                                       # a small shelf with a tea tin, bowls and a folded cloth
        G["wood"] += [("box", (0.09, 0, 0.0), (0.18, 0.7, 0.03), R0)]
        G["steel"] += [("cyl", (0.09, -0.22, 0.09), (0.05, 0.05, 0.15), R0)]; G["white"] += [("cyl", (0.09, 0.0, 0.05), (0.07, 0.04, 0.08), R0), ("cyl", (0.09, 0.14, 0.05), (0.07, 0.04, 0.08), R0)]
        G["blue"] += [("box", (0.09, 0.26, 0.04), (0.1, 0.12, 0.05), R0)]
        return G, 0.2
    for k in range(r.randint(2, 3)):                                                          # kitchen notices: white sheets with grey bars
        y = (k - 1) * 0.28 + r.uniform(-0.02, 0.02); hh = r.uniform(0.28, 0.36)
        G["white"] += [("box", (0.006, y, 0.2), (0.004, 0.22, hh), R0)]
        for q in range(4):
            G["ink"] += [("box", (0.009, y, 0.2 + hh / 2 - 0.05 - q * 0.06), (0.003, 0.15 * r.uniform(0.5, 1.0), 0.012), R0)]
    return G, 0.4


def _pendants(zc, stats):
    """R1: warm 2700 K pendants hung low over the counter (3-4): a lathed shade with a rolled rim, socket and bulb (proc_utensils.shade), a cord to the ceiling and a small spot each."""
    from room_planner import proc_utensils as pu
    cts = [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith("CafeCounterFactory")]
    if not cts:
        return 0
    cx0, cx1, cy0, cy1, _a, _b = _bb(cts[0]); n = int(os.environ.get("ROOM_RAMEN_PENDANTS") or 4); cx = (cx0 + cx1) / 2
    cord = pa._flat("ir_rd_pcord", (0.02, 0.02, 0.02), 0.6)
    zl = 1.72                                                                             # shade bottom height: low over the counter, clear of eye level for the stools
    h = 0.16; cords = []
    for k in range(n):
        y = cy0 + (k + 0.5) * (cy1 - cy0) / n
        so = pu.shade(0.14, h); so.name = f"RamenPendantShade_{k}"; so.location = (cx, y, zl + h); so["src"] = "arch:ramen_dressing"
        cords += [("cyl", (cx, y, zl + h), (cx, y, zc), 0.004, 6)]
        ld = bpy.data.lights.new(f"ir_rd_pendant_{k}", "SPOT"); ld.energy = 45.0; ld.spot_size = math.radians(80); ld.spot_blend = 0.4; ld.color = (1.0, 0.68, 0.4); ld.shadow_soft_size = 0.04
        lo = bpy.data.objects.new(f"PointLampFactory(ramen_pendant).spawn_asset({k})", ld); bpy.context.scene.collection.objects.link(lo); lo.location = (cx, y, zl - 0.02)
    fl.mesh_object("RamenPendants", [(cord, cords)], bevel=False)
    return n


def _contrast(stats):
    """R1: dim every fill light (not ours, not the sun) by ROOM_RAMEN_FILL and the world by ROOM_RAMEN_WORLD."""
    fill = float(os.environ.get("ROOM_RAMEN_FILL") or 0.35); world = float(os.environ.get("ROOM_RAMEN_WORLD") or 0.3); nl = 0
    for L in bpy.data.objects:
        if L.type == "LIGHT" and not L.name.startswith(("ir_rd_", "ir_real_sun", "SpotLampFactory(ramen", "AreaLampFactory(ramen", "PointLampFactory(ramen")) and "ramen" not in L.name and not L.get("ir_rd_scaled"):
            L.data.energy *= fill; L["ir_rd_scaled"] = 1; nl += 1
    w = bpy.context.scene.world
    if w is not None and w.use_nodes:
        for n in w.node_tree.nodes:
            if n.type == "BACKGROUND" and not n.get("ir_rd_scaled"):
                n.inputs["Strength"].default_value *= world; n["ir_rd_scaled"] = 1
    return nl


def _notices(files, rng, far_x, k_west, y0, y1, x0, x1, used_y):
    """Small taped paper notices from the generated notice_*.png: the first by the ticket machine (on the wall behind it), the next two on the customer wall in the gaps between menu pieces."""
    made = 0; tape = pa._flat("ir_rd_tape", (0.85, 0.8, 0.65), 0.7)
    def paper(name, path, loc, yaw, tilt):
        nonlocal made
        w, h = 0.21, 0.28
        G = [(_img_mat(path), [("box", (0.004, 0, h / 2), (0.004, w, h), (0, 0, 0))]), (tape, [("box", (0.007, -w / 2 + 0.03, h - 0.01), (0.002, 0.045, 0.02), (0, 0, 0.5)), ("box", (0.007, w / 2 - 0.03, h - 0.01), (0.002, 0.045, 0.02), (0, 0, -0.5))])]
        o = pa._prims(name, G); o.rotation_euler = (tilt, 0, yaw); o.location = loc; o["src"] = "arch:ramen_dressing"; made += 1
    tm = [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith("TicketMachineFactory")]
    files = list(files); rng.shuffle(files)
    if tm:
        bx0, bx1, by0, by1, _bz0, _bz1 = _bb(tm[0]); cx, cy = (bx0 + bx1) / 2, (by0 + by1) / 2
        d = {"x0": cx - x0, "x1": x1 - cx, "y0": cy - y0, "y1": y1 - cy}; wall = min(d, key=d.get)                       # the wall the machine stands against
        off = 0.42 if rng.random() < 0.5 else -0.42
        if wall in ("x0", "x1"):
            paper("RamenNotice(machine)", files[0], (x0 + 0.012 if wall == "x0" else x1 - 0.012, cy + off, 1.45), 0.0 if wall == "x0" else math.pi, math.radians(rng.uniform(-4, 4)))
        else:
            paper("RamenNotice(machine)", files[0], (cx + off, y0 + 0.012 if wall == "y0" else y1 - 0.012, 1.45), math.pi / 2 if wall == "y0" else -math.pi / 2, math.radians(rng.uniform(-4, 4)))
    ys = sorted(used_y)
    gaps = [(a + b) / 2 for a, b in zip(ys, ys[1:]) if b - a > 0.7]
    for k, yg in enumerate(gaps[:2]):
        paper(f"RamenNotice(wall{k})", files[(k + 1) % len(files)], (far_x + (-0.012 if k_west else 0.012), yg, rng.uniform(1.3, 1.5)), math.pi if k_west else 0.0, math.radians(rng.uniform(-4, 4)))
    return made


def _tone(stats):
    """R1b: warm / darken the wall and ceiling materials (ROOM_RAMEN_WALL_TONE default 0.7, ROOM_RAMEN_CEILING_TONE default 0.5 = base colour multiplier): bright off-white shells washed the room."""
    wt = float(os.environ.get("ROOM_RAMEN_WALL_TONE") or 0.7); ct = float(os.environ.get("ROOM_RAMEN_CEILING_TONE") or 0.5); n = 0; seen = set()
    for o in bpy.data.objects:
        if o.type != "MESH":
            continue
        f = ct if o.name.endswith(".ceiling") else wt if o.name.endswith(".wall") else None
        if f is None:
            continue
        for ms in o.material_slots:
            m = ms.material
            if m is None or not m.use_nodes or (m.name, f) in seen or m.get("ir_rd_tone"):
                continue
            seen.add((m.name, f)); b = next((x for x in m.node_tree.nodes if x.type == "BSDF_PRINCIPLED"), None)
            if b is None:
                continue
            N, Lk = m.node_tree.nodes, m.node_tree.links; bc = b.inputs["Base Color"]
            mix = N.new("ShaderNodeMix"); mix.data_type = "RGBA"; mix.blend_type = "MULTIPLY"; mix.inputs["Factor"].default_value = 1.0; mix.inputs["B"].default_value = (f, f * 0.96, f * 0.88, 1.0)         # warm: blue a little lower
            if bc.links:
                src = bc.links[0].from_socket
                for l in list(bc.links):
                    Lk.remove(l)
                Lk.new(src, mix.inputs["A"])
            else:
                mix.inputs["A"].default_value = bc.default_value
            Lk.new(mix.outputs["Result"], bc); m["ir_rd_tone"] = 1; n += 1
    return n


def _counter(stats):
    """R2: the counter's top gets a fine procedural grain + a dark edge band, its front panel a darker material."""
    import bmesh
    cts = [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith("CafeCounterFactory")]
    front_kind = os.environ.get("ROOM_RAMEN_COUNTER_FRONT") or "dark"
    out = 0
    for o in cts:
        if (o.get("ir_rd_counter") or 0) >= 2:                                                    # version 2 = veneer front (r16); an r15-built counter is rebuilt once
            continue
        for ch in [c for c in o.children if c.name.startswith("RamenCounterEdgeBand")]:
            bpy.data.objects.remove(ch, do_unlink=True)
        for ms in o.material_slots:
            m = ms.material
            if m is None:
                continue
            if m.name.startswith("ir_counter_top") or m.name == "ir_rd_counter_top_wood":                                          # the top slab: fine grain along the length (object y), two tones + pores
                nm = bpy.data.materials.get("ir_rd_counter_top_wood")
                if nm is None:
                    nm = bpy.data.materials.new("ir_rd_counter_top_wood"); nm.use_nodes = True; nt = nm.node_tree; N, Lk = nt.nodes, nt.links; b = nt.nodes["Principled BSDF"]
                    tc = N.new("ShaderNodeTexCoord"); mp = N.new("ShaderNodeMapping"); Lk.new(tc.outputs["Object"], mp.inputs["Vector"]); mp.inputs["Scale"].default_value = (1.0, 0.12, 1.0)      # features stretched ~8x along the length (y)
                    wv = N.new("ShaderNodeTexWave"); wv.wave_type = "BANDS"; wv.bands_direction = "X"; wv.inputs["Scale"].default_value = 55.0; wv.inputs["Distortion"].default_value = 5.0; wv.inputs["Detail"].default_value = 2.0; wv.inputs["Detail Scale"].default_value = 2.5
                    Lk.new(mp.outputs["Vector"], wv.inputs["Vector"])
                    nz = N.new("ShaderNodeTexNoise"); nz.inputs["Scale"].default_value = 60.0; nz.inputs["Detail"].default_value = 4.0; Lk.new(mp.outputs["Vector"], nz.inputs["Vector"])
                    mx = N.new("ShaderNodeMix"); mx.data_type = "FLOAT"; mx.inputs["Factor"].default_value = 0.35; Lk.new(wv.outputs["Fac"], mx.inputs["A"]); Lk.new(nz.outputs["Fac"], mx.inputs["B"])
                    ramp = N.new("ShaderNodeValToRGB"); ramp.color_ramp.elements[0].color = (0.42, 0.22, 0.08, 1); ramp.color_ramp.elements[1].color = (0.66, 0.42, 0.18, 1)
                    Lk.new(mx.outputs["Result"], ramp.inputs["Fac"]); Lk.new(ramp.outputs["Color"], b.inputs["Base Color"]); b.inputs["Roughness"].default_value = 0.4
                ms.material = nm
            elif (m.name.startswith("ir_counter_") and "top" not in m.name) or m.name.startswith("ir_rd_counter_front"):                    # the front panel
                rgb, rough, met = {"dark": ((0.07, 0.045, 0.03), 0.4, 0.0), "black": ((0.025, 0.025, 0.028), 0.35, 0.0), "steel": ((0.62, 0.64, 0.66), 0.3, 1.0)}.get(front_kind, ((0.07, 0.045, 0.03), 0.4, 0.0))
                nm = bpy.data.materials.get(f"ir_rd_counter_front_veneer_{front_kind}")
                if nm is None:                                                              # calm veneer: wide vertical panels (0.18 m) each with its own slight tone, a very faint long grain; no scanned scratch detail
                    nm = bpy.data.materials.new(f"ir_rd_counter_front_veneer_{front_kind}"); nm.use_nodes = True; nt = nm.node_tree; N, Lk = nt.nodes, nt.links; b = nt.nodes["Principled BSDF"]
                    tc = N.new("ShaderNodeTexCoord"); sp = N.new("ShaderNodeSeparateXYZ"); Lk.new(tc.outputs["Object"], sp.inputs["Vector"])
                    pl = N.new("ShaderNodeMath"); pl.operation = "DIVIDE"; Lk.new(sp.outputs["Y"], pl.inputs[0]); pl.inputs[1].default_value = 0.18
                    fl_ = N.new("ShaderNodeMath"); fl_.operation = "FLOOR"; Lk.new(pl.outputs[0], fl_.inputs[0])
                    wn = N.new("ShaderNodeTexWhiteNoise"); wn.noise_dimensions = "1D"; Lk.new(fl_.outputs[0], wn.inputs["W"])
                    tone = N.new("ShaderNodeMath"); tone.operation = "MULTIPLY_ADD"; Lk.new(wn.outputs["Value"], tone.inputs[0]); tone.inputs[1].default_value = 0.22; tone.inputs[2].default_value = 0.89            # panel tone 0.89 .. 1.11
                    gr = N.new("ShaderNodeTexWave"); gr.wave_type = "BANDS"; gr.bands_direction = "Z"; gr.inputs["Scale"].default_value = 9.0; gr.inputs["Distortion"].default_value = 1.5; Lk.new(tc.outputs["Object"], gr.inputs["Vector"])
                    gm = N.new("ShaderNodeMath"); gm.operation = "MULTIPLY_ADD"; Lk.new(gr.outputs["Fac"], gm.inputs[0]); gm.inputs[1].default_value = 0.06; gm.inputs[2].default_value = 0.97                        # grain 0.97 .. 1.03
                    tm = N.new("ShaderNodeMath"); tm.operation = "MULTIPLY"; Lk.new(tone.outputs[0], tm.inputs[0]); Lk.new(gm.outputs[0], tm.inputs[1])
                    cv = N.new("ShaderNodeCombineColor"); sc_ = N.new("ShaderNodeVectorMath"); sc_.operation = "SCALE"; sc_.inputs[0].default_value = rgb; Lk.new(tm.outputs[0], sc_.inputs["Scale"])
                    Lk.new(sc_.outputs["Vector"], b.inputs["Base Color"]); b.inputs["Roughness"].default_value = rough; b.inputs["Metallic"].default_value = met
                ms.material = nm
        # the edge band round the top slab (the vertices of the topmost 4 cm), a 4 mm proud dark strip, parented to the counter
        co = [v.co for v in o.data.vertices]; zt = max(c.z for c in co); top = [c for c in co if c.z > zt - 0.012]
        if len(top) >= 4:
            x0, x1 = min(c.x for c in top), max(c.x for c in top); y0, y1 = min(c.y for c in top), max(c.y for c in top); t = 0.04; zc_ = zt - t / 2; e = 0.004
            band = pa._flat("ir_rd_counter_edge", (0.06, 0.035, 0.02), 0.35)
            bm = bmesh.new(); ax = (Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1)))
            for c, sz in ((Vector(((x0 + x1) / 2, y0 - e / 2, zc_)), (x1 - x0 + 2 * e, e, t)), (Vector(((x0 + x1) / 2, y1 + e / 2, zc_)), (x1 - x0 + 2 * e, e, t)),
                          (Vector((x0 - e / 2, (y0 + y1) / 2, zc_)), (e, y1 - y0, t)), (Vector((x1 + e / 2, (y0 + y1) / 2, zc_)), (e, y1 - y0, t))):
                r_ = bmesh.ops.create_cube(bm, size=1.0)
                for v in r_["verts"]:
                    x, y, z = v.co; v.co = c + ax[0] * (x * sz[0]) + ax[1] * (y * sz[1]) + ax[2] * (z * sz[2])
                for f in {f for v in r_["verts"] for f in v.link_faces}:
                    f.material_index = 0
            me = bpy.data.meshes.new("RamenCounterEdge"); bm.to_mesh(me); bm.free(); me.materials.append(band)
            ob = bpy.data.objects.new("RamenCounterEdgeBand", me); bpy.context.scene.collection.objects.link(ob); ob.parent = o; ob["src"] = "arch:ramen_dressing"
        o["ir_rd_counter"] = 2; out += 1
    return out


def apply(stats):
    if os.environ.get("ROOM_RAMEN_DRESSING") != "1":
        return 0
    for o in [x for x in bpy.data.objects if x.name.startswith(("RamenWallDecor", "RamenNotice", "RamenDownlights", "RamenPendants", "RamenPendantShade", "SpotLampFactory(ramen", "AreaLampFactory(ramen", "PointLampFactory(ramen_pendant"))]:
        bpy.data.objects.remove(o, do_unlink=True)                                           # idempotent: a kit pass re-run on an already-dressed blend rebuilds, it does not stack a second set
    cs = [o for o in bpy.data.objects if o.type == "MESH" and o.name.endswith(".ceiling")]
    ks = [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith("RamenKitchenFactory")]
    if not cs:
        print("RAMEN_DRESSING skipped: no ceiling object", flush=True)
        return 0
    rng = random.Random(32)
    x0, x1, y0, y1, _z0, zc = _bb(cs[0]); zc = _bb(cs[0])[4]
    if ks:
        kx0, kx1, ky0, ky1, _a, _b = _bb(ks[0]); anchor = "RamenKitchenFactory"
    else:                                                                                     # no kitchen block (a layout that listed the line piece by piece): anchor on the counter, else on the west wall
        cts = [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith("CafeCounterFactory")]
        if cts:
            kx0, kx1, ky0, ky1, _a, _b = _bb(cts[0]); anchor = "CafeCounterFactory"
        else:
            kx0, kx1, ky0, ky1, anchor = x0, x0 + 1.2, y0, y1, "room (west wall)"
    print(f"RAMEN_DRESSING anchor={anchor} room x[{x0:.2f},{x1:.2f}] y[{y0:.2f},{y1:.2f}] ceiling z={zc:.2f}", flush=True)
    k_west = (kx0 + kx1) / 2 < (x0 + x1) / 2                                                  # the kitchen stands against the west or the east wall
    far_x = x1 if k_west else x0
    n_l = n_d = 0
    if os.environ.get("ROOM_RAMEN_LIGHTS", "1") != "0":
        for o in list(bpy.data.objects):
            if o.type == "MESH" and o.name.startswith("AboCeilingFixtureFactory"):
                bpy.data.objects.remove(o, do_unlink=True)
        for o in list(bpy.data.objects):
            if o.type == "LIGHT" and "(pendant)" in o.name:
                bpy.data.objects.remove(o, do_unlink=True)
        disc = pa._flat("ir_rd_downlight", (1.0, 0.85, 0.6), 0.4); b = disc.node_tree.nodes["Principled BSDF"]
        b.inputs["Emission Color"].default_value = (1.0, 0.8, 0.5, 1); b.inputs["Emission Strength"].default_value = 12.0
        rows = [((x1 if k_west else x0) + (-1 if k_west else 1) * 0.55), ((kx1 if k_west else kx0) + (1 if k_west else -1) * 0.95)]      # a row over the stools side and one over the counter / aisle
        parts = []
        for xr in rows:
            for k in range(int((y1 - y0 - 0.6) / 0.9) + 1):
                y = y0 + 0.5 + k * 0.9
                if y > y1 - 0.3:
                    break
                parts.append(("cyl", (xr, y, zc - 0.004), (xr, y, zc - 0.012), 0.05, 14))
                ld = bpy.data.lights.new(f"ir_rd_spot_{n_l}", "SPOT"); ld.energy = 30.0 if os.environ.get("ROOM_RAMEN_CONTRAST", "1") != "0" else 22.0; ld.spot_size = math.radians(35 if os.environ.get("ROOM_RAMEN_CONTRAST", "1") != "0" else 70); ld.spot_blend = 0.3 if os.environ.get("ROOM_RAMEN_CONTRAST", "1") != "0" else 0.5; ld.color = (1.0, 0.78, 0.5); ld.shadow_soft_size = 0.05
                lo = bpy.data.objects.new(f"SpotLampFactory(ramen).spawn_asset({n_l})", ld); bpy.context.scene.collection.objects.link(lo)
                lo.location = (xr, y, zc - 0.03); n_l += 1
        fl.mesh_object("RamenDownlights", [(disc, parts)], bevel=False)
        ka = bpy.data.lights.new("ir_rd_hood_light", "AREA"); ka.shape = "RECTANGLE"; ka.size = 1.0; ka.size_y = max(1.0, (ky1 - ky0) * 0.5); ka.energy = 150.0; ka.color = (0.82, 0.9, 1.0)
        ko = bpy.data.objects.new("AreaLampFactory(ramen_hood).spawn_asset(0)", ka); bpy.context.scene.collection.objects.link(ko)
        ko.location = ((kx0 + kx1) / 2 + (0.35 if k_west else -0.35), (ky0 + ky1) / 2 + (ky1 - ky0) * 0.12, 1.76); n_l += 1                # under the hood, cool white, pointing down
    used_y_ = []
    if os.environ.get("ROOM_RAMEN_DECOR", "1") != "0":
        blocked = []
        for o in bpy.data.objects:
            if o.type == "MESH" and (o.name.startswith(("window", "door", "Window", "DoorCasing", "MenuBoard"))):
                bx0, bx1, by0, by1, bz0, bz1 = _bb(o)
                if abs(((bx0 + bx1) / 2) - far_x) < 0.6:
                    blocked.append((by0 - 0.35, by1 + 0.35))
        boards_, strips_, posters_ = _gfx("menu_board"), _gfx("menu_strip"), _gfx("poster")
        used_y_ = []
        kinds = ["board", "papers", "tags", "hooks", "shelf", "notices", "board", "papers"]
        if posters_:
            kinds = ["board", "papers", "poster", "hooks", "shelf", "poster", "board", "papers"]
        rng.shuffle(kinds)
        print(f"RAMEN_DRESSING graphics: boards={len(boards_)} strips={len(strips_)} posters={len(posters_)} from {GRAPHICS}", flush=True)
        slots = [y0 + 0.55 + k * 0.95 for k in range(int((y1 - y0 - 0.8) / 0.95) + 1)]
        for k, y in enumerate(slots[:len(kinds)]):
            if y > y1 - 0.4 or any(a < y < b for a, b in blocked):
                continue
            gk = {"board": boards_, "papers": strips_, "poster": posters_}.get(kinds[k]) or None
            if gk:
                gk = [gk[(k + q) % len(gk)] for q in range(len(gk))]                            # a different starting picture per piece
            G, h = _decor(kinds[k], rng, gk)
            mats = {"wood": pa._flat("ir_rd_wood", (0.38, 0.2, 0.08), 0.5, wood=True), "card": pa._flat("ir_rd_card", (0.9, 0.86, 0.74), 0.6), "ink": pa._flat("ir_rd_ink", (0.03, 0.025, 0.02), 0.6),
                    "red": pa._flat("ir_rd_red", (0.6, 0.04, 0.03), 0.5), "white": pa._flat("ir_rd_paper", (0.93, 0.93, 0.9), 0.6), "steel": pa._flat("ir_rd_steel", (0.7, 0.72, 0.74), 0.3, 1.0), "blue": pa._flat("ir_rd_blue", (0.04, 0.1, 0.3), 0.6)}
            o = pa._prims(f"RamenWallDecor({kinds[k]}|{k})", [(mats[m], G[m]) for m in ("wood", "card", "ink", "red", "white", "steel", "blue")] + [(_img_mat(pth), prims) for pth, prims in G.get("__img", [])])
            zb = rng.uniform(1.05, 1.5) if kinds[k] in ("board", "papers", "notices") else (1.35 if kinds[k] != "shelf" else 1.15)
            o.rotation_euler = (0, 0, math.pi if k_west else 0.0); o.location = (far_x + (-0.012 if k_west else 0.012), y, zb); n_d += 1; used_y_.append(y)
    notices_ = _gfx("notice_")
    if notices_ and os.environ.get("ROOM_RAMEN_DECOR", "1") != "0":                           # r19: handwritten paper notices (~21 x 28 cm, taped, slight tilt): one by the ticket machine / entrance, two on the customer wall between the menu pieces
        n_d += _notices(notices_, rng, far_x, k_west, y0, y1, x0, x1, [y for y in used_y_])
    if os.environ.get("ROOM_RAMEN_CONTRAST", "1") != "0":
        n_p = _pendants(zc, stats); n_f = _contrast(stats); n_l += n_p; n_t = _tone(stats)
        print(f"RAMEN_DRESSING contrast: pendants={n_p} fills_dimmed={n_f} wall/ceiling materials toned={n_t}", flush=True)
    if os.environ.get("ROOM_RAMEN_COUNTER", "1") != "0":
        print(f"RAMEN_DRESSING counter: {_counter(stats)} rebuilt", flush=True)
    print(f"RAMEN_DRESSING done: lights={n_l} decor={n_d} (fixtures removed: AboCeilingFixtureFactory + pendant lights)", flush=True)
    stats["ramen_dressing"] = {"lights": n_l, "decor": n_d, "anchor": anchor}
    return n_l + n_d
