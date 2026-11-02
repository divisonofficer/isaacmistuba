"""Generic floor-to-ceiling glass wall with a real view and sun patches (generalised from rooftop_shell). Opt-in: ROOM_BIGGLASS=street|skyline|garden.

    big_glass.apply(L, S, zc, at, name, rng, stats, room=None)     called from architecture_pass.build() for every room when the flag is set
    big_glass.bigglass_views(at, L, S, side)                       -> 3 camera dicts in the pipeline's VIEWS format (also in stats['bigglass']['views'])
    big_glass.make_card(kind, path)                                a generated exterior card PNG (no real photo)

Per room (service rooms, rooms shorter than 4 m or narrower than 3 m are skipped):
  * the glass side is the long wall (v = 0 or v = S) with more window objects near it, else v = S; there the wall faces (and the exterior shell's) between 0.5 m piers are
    removed up to zc - 0.15, existing window MESHES in that band are deleted (their portal lights stay: the DAY scaling still applies)
  * dark mullions every 1.5-2 m plus a head and sill rail, clear thin glass panes with the shadow-ray trick (rooftop_shell._glass)
  * an emissive card 16 m outside (street / skyline / garden, generated), transparent to shadow rays so the sun reaches the glass
  * a SUN lamp (BIGGLASS_SUN W/m2, default 4, elevation 35 deg, 20 deg off the wall normal) shining through the glass: window patches on the floor
Env: BIGGLASS_ROOMS (comma list of room types that get glass; default all), BIGGLASS_CARD_EMIT (card emission, default 2.5), BIGGLASS_SUN, BIGGLASS_FRAME=white|black (default black).
"""
from __future__ import annotations

import math
import os
import random
from pathlib import Path

import bmesh
import bpy
from mathutils import Vector

from room_planner import proc_boutique_flagship as fl
from room_planner import rooftop_shell as rs

CARDS = Path("/jarvis/project/robomituba/data/venue_refs/bigglass_cards")
KINDS = ("street", "skyline", "garden", "street_night")
SERVICE = ("restroom", "utility", "closet", "bathroom")


def make_card(kind, path=None, w=4096, h=768, seed=11):
    from PIL import Image, ImageDraw, ImageFilter
    rng = random.Random(seed + KINDS.index(kind)); path = Path(path or CARDS / f"{kind}.png")
    im = Image.new("RGB", (w, h)); d = ImageDraw.Draw(im)
    for y in range(h):                                                       # daylight sky, paler toward the horizon
        t = y / h; d.line((0, y, w, y), fill=(int(110 + 110 * t), int(160 + 70 * t), int(225 + 20 * t)))
    for _ in range(26):                                                      # clouds
        cx, cy = rng.randint(0, w), rng.randint(40, int(h * 0.4))
        for _ in range(7):
            r = rng.randint(30, 80); ox = rng.randint(-120, 120)
            d.ellipse((cx + ox - r * 2, cy - r, cx + ox + r * 2, cy + r), fill=(246, 248, 250))
    im = im.filter(ImageFilter.GaussianBlur(5)); d = ImageDraw.Draw(im)
    ground = h - int(h * (0.2 if kind == "street" else 0.14))

    def building(x, bw, top, col, win, lit):
        d.rectangle((x, top, x + bw, ground), fill=col)
        for wy in range(top + 14, ground - 30, 26):
            for wx in range(x + 10, x + bw - 16, 24):
                d.rectangle((wx, wy, wx + 12, wy + 16), fill=win if rng.random() > 0.15 else lit)

    def tree(x, base, hgt, greens):
        d.rectangle((x - 5, base - hgt * 0.5, x + 5, base), fill=(72, 52, 36))
        for _ in range(14):
            r = rng.randint(int(hgt * 0.12), int(hgt * 0.22))
            ox, oy = rng.randint(-int(hgt * 0.25), int(hgt * 0.25)), rng.randint(-int(hgt * 0.2), int(hgt * 0.2))
            c = rng.choice(greens); d.ellipse((x + ox - r, base - hgt * 0.75 + oy - r, x + ox + r, base - hgt * 0.75 + oy + r), fill=c)

    if kind == "skyline":
        for layer, (col, hmax, win) in enumerate((((176, 192, 210), 330, (200, 214, 230)), ((138, 156, 180), 420, (176, 196, 222)), ((96, 116, 144), 520, (150, 176, 208)))):
            x = -rng.randint(0, 60)
            while x < w:
                bw = rng.randint(60, 170); building(x, bw, ground - rng.randint(120, hmax), col, win, (250, 240, 200)); x += bw + rng.randint(0, 20)
        d.rectangle((0, ground, w, h), fill=(150, 160, 150))
    elif kind == "street":
        x = -rng.randint(0, 80)
        while x < w:                                                         # brick fronts, 4-6 storeys
            bw = rng.randint(150, 300); col = rng.choice(((158, 84, 66), (176, 104, 76), (140, 92, 78), (190, 150, 118), (120, 78, 66)))
            building(x, bw, ground - rng.randint(300, 520), col, (60, 82, 104), (250, 236, 190)); x += bw + rng.randint(0, 6)
        d.rectangle((0, ground, w, h), fill=(104, 106, 110))
        d.rectangle((0, ground, w, ground + 26), fill=(176, 172, 164))       # pavement
        for x in range(0, w, 160):
            d.rectangle((x, ground + 70, x + 70, ground + 76), fill=(220, 220, 210))
        for x in range(60, w, 330):                                          # plane trees along the kerb
            tree(x + rng.randint(-40, 40), ground + 20, rng.randint(330, 430), ((52, 110, 48), (72, 132, 58), (40, 92, 44), (96, 150, 70)))
    else:
        d.rectangle((0, int(h * 0.55), w, h), fill=(86, 140, 70))
        for layer, (greens, hgt, n) in enumerate((((((44, 86, 50), (52, 98, 60))), 380, 34), (((60, 114, 54), (78, 134, 60)), 460, 28), (((88, 150, 64), (116, 172, 74), (70, 130, 58)), 560, 22))):
            for _ in range(n):
                tree(rng.randint(0, w), ground - 40 + layer * 40, hgt * rng.uniform(0.7, 1.1), greens)
        for _ in range(500):                                                 # flowers
            x, y = rng.randint(0, w), rng.randint(ground, h - 4)
            d.ellipse((x, y, x + 8, y + 8), fill=rng.choice(((240, 230, 120), (230, 120, 150), (250, 250, 250), (200, 140, 230))))
    path.parent.mkdir(parents=True, exist_ok=True)
    im = im.filter(ImageFilter.GaussianBlur(2.0)); im = Image.blend(im, Image.merge("RGB", [Image.effect_noise((w, h), 18)] * 3), 0.06); im.save(path)
    return path


def photo_card(kind, w=4096, h=768):
    """data/venue_refs/bigglass_cards/src/<kind>.png (a generated photographic panorama) -> <kind>_photo.png, resized to height h, NOT tiled (a mirrored seam showed as a symmetric reflection in S18); returns (path, aspect, ground rgb)."""
    from PIL import Image
    src = CARDS / "src" / f"{kind}.png"
    if kind == "skyline" and os.environ.get("ROOM_TERRACE_PLATE"):                     # P2b r38: the terrace + glazing skyline was the NIGHT panorama; a named daytime plate (e.g. skyline_day_02) replaces it
        src = CARDS / "src" / f"env_{os.environ['ROOM_TERRACE_PLATE']}.png"
    if not src.exists():
        return None
    out = CARDS / f"{kind}_photo.png"
    im = Image.open(src).convert("RGB"); sh = h / im.height; im = im.resize((max(1, int(im.width * sh)), h), Image.LANCZOS)
    im.save(out)
    px = im.crop((0, int(h * 0.9), im.width, h)).resize((1, 1), Image.BOX).getpixel((0, 0))
    return out, im.width / h, tuple(round((c / 255) ** 2.2, 3) for c in px)


def _side(at, L, S, zc):
    """+1 = glass on v = S, -1 = on v = 0: the long wall with more window meshes within 1.5 m, else v = S."""
    o0 = Vector((*at(0, 0), 0)); ux = Vector((*at(1, 0), 0)) - o0; vx = Vector((*at(0, 1), 0)) - o0
    score = {1: 0, -1: 0}
    for o in bpy.data.objects:
        if "Window" in o.name and o.type == "MESH":
            d = o.matrix_world.translation - o0; u, v = d.dot(ux), d.dot(vx)
            if -0.5 < u < L + 0.5:
                score[1] += abs(v - S) < 1.5; score[-1] += abs(v) < 1.5
    return -1 if score[-1] > score[1] else 1


def bigglass_views(at, L, S, side=1, zc=3.0):
    """Three cameras: along the glass wall in both directions (1.3 m in front of it) and one from inside toward the glass centre. VIEWS format."""
    vg = S if side > 0 else 0.0; vin = lambda d: vg - side * d
    cam = lambda n, u0, v0, u1, v1, z1: {"name": n, "location": [*(round(c, 2) for c in at(u0, v0)), 1.5], "target": [*(round(c, 2) for c in at(u1, v1)), z1], "hfov": 80.0, "res": [512, 384]}
    return [cam("bigglass_a", 1.2, vin(1.3), L * 0.85, vin(0.4), 1.4), cam("bigglass_b", L - 1.2, vin(1.3), L * 0.15, vin(0.4), 1.4),
            cam("bigglass_c", L * 0.5, vin(min(S * 0.55, 5.0)), L * 0.5, vg, 1.6)]


def _card(kind, at, L, side, S, uc=None):
    """-> (card quad corners, material, ground quad corners, ground rgb): the card stands 16 m outside; its horizon row sits at eye height (1.5 m) so a photo reads right;
    a ground plane at z = -0.02 fills the strip between the wall and the card (no black band)."""
    ph = photo_card(kind)
    if ph:
        path, aspect, ground = ph; hf = float(os.environ.get("BIGGLASS_HORIZON") or {"street": 0.30, "garden": 0.38, "skyline": 0.62, "street_night": 0.30}[kind])   # horizon row of each photo, from its bottom edge
    else:                                                                    # the generated fallback
        path = CARDS / f"{kind}.png"
        if not path.exists():
            make_card(kind, path)
        aspect, hf = 4096 / 768, {"street": 0.2, "skyline": 0.14, "garden": 0.14}[kind]
        ground = {"street": (0.14, 0.14, 0.15), "skyline": (0.3, 0.32, 0.3), "garden": (0.1, 0.2, 0.06)}[kind]
    m = bpy.data.materials.get(f"ir_bg_card_{kind}")
    if m is None:
        m = bpy.data.materials.new(f"ir_bg_card_{kind}"); m.use_nodes = True
        N, Lk = m.node_tree.nodes, m.node_tree.links; b = N["Principled BSDF"]
        t = N.new("ShaderNodeTexImage"); t.image = bpy.data.images.load(str(path), check_existing=True)
        src_ = t.outputs["Color"]
        if float(os.environ.get("BIGGLASS_CARD_CONTRAST", "0") or 0) != 0:           # BIGGLASS_CARD_CONTRAST=0.3..0.6 (Blender's -1..1 scale): a hazy photo (skyline) gets contrast (P2b r26 bedroom: 'a washed-out haze, almost no detail')
            bc_ = N.new("ShaderNodeBrightContrast"); bc_.inputs["Contrast"].default_value = float(os.environ["BIGGLASS_CARD_CONTRAST"]) * 100.0 if abs(float(os.environ["BIGGLASS_CARD_CONTRAST"])) <= 1.0 else float(os.environ["BIGGLASS_CARD_CONTRAST"])
            Lk.new(t.outputs["Color"], bc_.inputs["Color"]); src_ = bc_.outputs["Color"]
        Lk.new(src_, b.inputs["Emission Color"]); b.inputs["Emission Strength"].default_value = float(os.environ.get("BIGGLASS_CARD_EMIT", "2.5"))
        b.inputs["Base Color"].default_value = (0, 0, 0, 1); b.inputs["Roughness"].default_value = 1.0
        out = next(n for n in N if n.type == "OUTPUT_MATERIAL"); lp = N.new("ShaderNodeLightPath"); tr = N.new("ShaderNodeBsdfTransparent"); mx = N.new("ShaderNodeMixShader")
        Lk.new(lp.outputs["Is Shadow Ray"], mx.inputs["Fac"]); Lk.new(b.outputs["BSDF"], mx.inputs[1]); Lk.new(tr.outputs["BSDF"], mx.inputs[2]); Lk.new(mx.outputs["Shader"], out.inputs["Surface"])
    v = S + 16.0 if side > 0 else -16.0
    uc = L / 2 if uc is None else uc                                       # the photo is centred on the window: its middle, not an edge, is what the glass shows
    wid = 90.0 if ph else L + 120.0; u0, u1 = uc - wid / 2, uc + wid / 2; H = wid / aspect; lift = float(os.environ.get("BIGGLASS_LIFT") or 0.0); zb = 1.5 - hf * H - lift      # BIGGLASS_LIFT=m: the view as from that many metres higher (an upper floor, B refs 'treetop view'): the horizon row sits lift m below the eye
    card = ((*at(u0, v), zb), (*at(u1, v), zb), (*at(u1, v), zb + H), (*at(u0, v), zb + H))
    v0 = S if side > 0 else 0.0
    gz = -0.02 - lift
    gq = ((*at(u0, v0), gz), (*at(u1, v0), gz), (*at(u1, v), gz), (*at(u0, v), gz))
    return card, m, gq, ground


def _photo_ground(oname, gq, kind):
    """The ground quad textured with the bottom strip of the card photo (near the wall = the photo's bottom row, at the card = 16 % up), emissive like the card."""
    gm = bpy.data.materials.get(f"ir_bg_groundphoto_{kind}")
    if gm is None:
        gm = bpy.data.materials.new(f"ir_bg_groundphoto_{kind}"); gm.use_nodes = True
        N, Lk = gm.node_tree.nodes, gm.node_tree.links; b = N["Principled BSDF"]
        t = N.new("ShaderNodeTexImage"); t.image = bpy.data.images.load(str(CARDS / f"{kind}_photo.png"), check_existing=True); t.extension = "EXTEND"
        uv = N.new("ShaderNodeUVMap"); mp = N.new("ShaderNodeMapping")
        sv = 0.16                                                        # rows of the photo the ground strip shows (0 at the wall .. sv at the card)
        if kind.startswith("env_") or os.environ.get("BIGGLASS_GROUND_MATCH", "1") != "0":     # all photo cards (B r23 ENV-01: the garden ground strip showed 0.16 of the photo but the card's row at z = 0 is hf - 1.5 / H, ~0.29: a grey slab with a hard edge); BIGGLASS_GROUND_MATCH=0 restores 0.16
            #: a window panorama's card row at z = 0 is hf - 1.5 / H, not 0.16 -> a hard seam where the ground met the card
            ph_ = photo_card(kind); hf_ = float(os.environ.get("BIGGLASS_HORIZON") or {"street": 0.30, "garden": 0.38, "skyline": 0.62, "street_night": 0.30}.get(kind, 0.36))
            if ph_:
                sv = min(0.6, max(0.05, hf_ - (1.5 + float(os.environ.get("BIGGLASS_LIFT") or 0.0)) / (90.0 / ph_[1])))
        mp.inputs["Scale"].default_value = (1.0, sv, 1.0)
        Lk.new(uv.outputs["UV"], mp.inputs["Vector"]); Lk.new(mp.outputs["Vector"], t.inputs["Vector"])
        Lk.new(t.outputs["Color"], b.inputs["Emission Color"]); b.inputs["Emission Strength"].default_value = float(os.environ.get("BIGGLASS_CARD_EMIT", "2.5"))
        b.inputs["Base Color"].default_value = (0, 0, 0, 1); b.inputs["Roughness"].default_value = 1.0
    me = bpy.data.meshes.new(oname); me.from_pydata([tuple(c) for c in gq], [], [(0, 1, 2, 3)]); me.update()
    uvl = me.uv_layers.new(name="UVMap")
    for li, uvv in zip(me.polygons[0].loop_indices, ((0, 0), (1, 0), (1, 1), (0, 1))):
        uvl.data[li].uv = uvv
    me.materials.append(gm)
    o = bpy.data.objects.new(oname, me); bpy.context.scene.collection.objects.link(o)
    return o


def _carve(obj, o0, ux, vx, vg, u0, u1, z0, z1, band):
    """Cut the rectangle u0..u1 x z0..z1 out of obj's wall plane v = vg: the band's faces are bisected along the 4 rectangle edges first (a wall built from a few big quads
    must not lose a whole quad), then the faces inside are deleted. Returns the faces removed."""
    if obj is None or obj.type != "MESH":
        return 0
    bm = bmesh.new(); bm.from_mesh(obj.data); mw = obj.matrix_world; inv = mw.inverted(); inv3 = inv.to_3x3()
    inband = lambda f: abs((mw @ f.calc_center_median() - o0).dot(vx) - vg) < band
    zax = Vector((0, 0, 1))
    for co, nrm in (((u0, 0), ux), ((u1, 0), ux), ((0, z0), zax), ((0, z1), zax)):
        faces = [f for f in bm.faces if inband(f)]
        geom = list({*faces, *(e for f in faces for e in f.edges), *(v for f in faces for v in f.verts)})
        p = (o0 + ux * co[0]) if nrm is ux else Vector((o0.x, o0.y, co[1]))
        bmesh.ops.bisect_plane(bm, geom=geom, dist=1e-4, plane_co=inv @ p, plane_no=(inv3 @ nrm).normalized())
    kill = []
    for f in bm.faces:
        c = mw @ f.calc_center_median(); d = c - o0
        if abs(d.dot(vx) - vg) < band and u0 < d.dot(ux) < u1 and z0 < c.z < z1:
            kill.append(f)
    bmesh.ops.delete(bm, geom=kill, context="FACES"); bm.to_mesh(obj.data); bm.free()
    return len(kill)


def _patch(wall, o0, ux, vx, vg, rects):
    """Add plain wall quads (u0, u1, z0, z1) on the plane v = vg to the room's own `.wall` mesh (material slot 0): head fascia, jambs and sill close the slivers the carve
    leaves, and being part of `.wall` they follow every later wall material (archtex paint, flat walls, tile wall) -- a separate box kept the old colour."""
    if wall is None or wall.type != "MESH" or not rects:
        return 0
    bm = bmesh.new(); bm.from_mesh(wall.data); inv = wall.matrix_world.inverted()
    for u0, u1, z0, z1 in rects:
        pts = [o0 + ux * u + vx * vg + Vector((0, 0, z)) for u, z in ((u0, z0), (u1, z0), (u1, z1), (u0, z1))]
        f = bm.faces.new([bm.verts.new(inv @ p) for p in pts]); f.material_index = 0
    bm.to_mesh(wall.data); bm.free()
    return len(rects)


def _door_wall(at, L, S):
    """BIGGLASS_SIDE=door: (wall, u) of the door casing that stands on the room's edge. wall: 'S' (v = S), '0' (v = 0), 'L' (u = L), 'U' (u = 0); u = the door centre along that wall."""
    o0 = Vector((*at(0, 0), 0)); ux = Vector((*at(1, 0), 0)) - o0; vx = Vector((*at(0, 1), 0)) - o0
    best = None
    for o in bpy.data.objects:
        if o.type != "MESH" or not o.name.startswith("DoorCasingFactory"):
            continue
        pts = [o.matrix_world @ Vector(c) for c in o.bound_box]; c = sum(pts, Vector()) / 8 - o0
        u, v = c.dot(ux), c.dot(vx)
        if not (-0.6 < u < L + 0.6 and -0.6 < v < S + 0.6):
            continue
        d = {"S": abs(v - S), "0": abs(v), "L": abs(u - L), "U": abs(u)}
        w = min(d, key=d.get)
        if d[w] < 0.6 and (best is None or d[w] < best[0]):
            best = (d[w], w, u if w in "S0" else v)
    return best[1:] if best else None


def _door_gaps(o0, ux, vx, vg, ua, ub):
    """[(u0, u1)] along the glass run where a door casing stands in the glass line: panes, mullions and the sill rail leave these gaps so the door opening stays open
    (user 2026-10-26: a zero-thickness glass plane across a door opening blocks it, and Mitsuba's dielectric refracts a one-sided plane into a round fisheye; 5 of floor C's 6 doors, S34/S35/cafe fronts)."""
    gaps = []
    for o in bpy.data.objects:
        if o.type != "MESH" or not o.name.startswith("DoorCasingFactory"):
            continue
        pts = [o.matrix_world @ Vector(c) for c in o.bound_box]
        c = sum(pts, Vector()) / len(pts)
        us = [((p - o0).dot(ux)) / max(1e-9, ux.length_squared) for p in pts]; vs = [((p - o0).dot(vx)) / max(1e-9, vx.length_squared) for p in pts]
        if abs((min(vs) + max(vs)) / 2 - vg) > 0.45:
            continue
        u0, u1 = min(us) + 0.06, max(us) - 0.06
        if u1 > ua - 0.1 and u0 < ub + 0.1 and u1 - u0 > 0.5:
            gaps.append((u0, u1))
    return sorted(gaps)


def _spans(a, b, gaps, minw=0.12):
    out, cur = [], a
    for g0, g1 in gaps:
        if g1 <= cur or g0 >= b:
            continue
        if g0 - cur >= minw:
            out.append((cur, g0))
        cur = max(cur, g1)
    if b - cur >= minw:
        out.append((cur, b))
    return out


def apply(L, S, zc, at, name, rng, stats, room=None, _side_force=None):
    kind = os.environ.get("ROOM_BIGGLASS", "")
    if kind == "street_night" and not (CARDS / "src" / "street_night.png").exists():
        return 0                                                              # a night card only from a generated photo: no cartoon fallback
    only = [x for x in os.environ.get("BIGGLASS_ROOMS", "").split(",") if x]                 # floors: glass only in these room types (e.g. open-office), not in every small room
    rt_ = str(room or "").split("_")[0]
    if kind not in KINDS or L < 4.0 or S < 3.0 or (rt_ in SERVICE and rt_ not in only):       # a service room is skipped unless BIGGLASS_ROOMS names its type (O2's atrium is a 'utility' room)
        return 0
    if only and str(room or "").split("_")[0] not in only:
        return 0
    if os.environ.get("BIGGLASS_SIDE") == "door" and _side_force is None:                  # glass on the wall that holds the entrance door (long or short wall)
        dw = _door_wall(at, L, S)
        if dw is not None:
            w, du = dw
            if w in "S0":
                return apply(L, S, zc, at, name, rng, stats, room, _side_force=(1 if w == "S" else -1, du))
            at2 = (lambda u, v: at(L - v, u)) if w == "U" else (lambda u, v: at(v, u))          # the short wall becomes the v = S wall of a turned frame
            return apply(S, L, zc, at2, name, rng, stats, room, _side_force=(1, du))
    side = _side(at, L, S, zc) if _side_force is None else _side_force[0]; vg = S if side > 0 else 0.0
    frac = min(1.0, float(os.environ.get("BIGGLASS_FRAC") or 1.0))          # 1 = floor-to-ceiling wall; < 1 = one window of that share of the wall (sill 0.9, head 2.1)
    if frac >= 1.0:
        ua, ub, z0, z1 = 0.3, L - 0.3, 0.0, zc - 0.15
    else:
        Lw = max(1.2, frac * (L - 1.0)); pos = os.environ.get("BIGGLASS_POS", "center")
        ua = 0.5 if pos == "start" else L - 0.5 - Lw if pos == "end" else (L - Lw) / 2
        ub = ua + Lw; z0, z1 = float(os.environ.get("BIGGLASS_SILL", "0.9")), float(os.environ.get("BIGGLASS_HEAD", "2.1"))
    if _side_force is not None:                                              # keep the door's casing and leaf inside the glass run
        du = _side_force[1]; ua = max(0.12, min(ua, du - 0.7)); ub = min(L - 0.12, max(ub, du + 0.7))
    o0 = Vector((*at(0, 0), 0)); ux = Vector((*at(1, 0), 0)) - o0; vx = Vector((*at(0, 1), 0)) - o0; gone = 0
    zlo = 0.02 if z0 <= 0.0 else z0
    removed = _carve(bpy.data.objects.get(f"{room}.wall") if room else None, o0, ux, vx, vg, ua, ub, zlo, z1, 0.35) + \
        _carve(bpy.data.objects.get(f"{room}.exterior") if room else None, o0, ux, vx, vg, ua, ub, zlo, z1 + 0.3, 0.7)
    wl = bpy.data.objects.get(f"{room}.wall") if room else None
    ztop = max(((wl.matrix_world @ Vector(c)).z for c in wl.bound_box), default=zc) if wl is not None else zc
    rects = [(ua - 0.12, ub + 0.12, z1, ztop), (ua - 0.12, ua, 0.0, ztop), (ub, ub + 0.12, 0.0, ztop)] + ([(ua - 0.12, ub + 0.12, 0.0, z0)] if z0 > 0.0 else [])
    patched = _patch(wl, o0, ux, vx, vg, rects)
    for o in list(bpy.data.objects):                                        # window meshes inside the opening: the opening replaces them (portal lights stay)
        if "Window" in o.name and o.type == "MESH":
            d = o.matrix_world.translation - o0
            if abs(d.dot(vx) - vg) < 1.0 and ua < d.dot(ux) < ub:
                bpy.data.objects.remove(o, do_unlink=True); gone += 1
    frame_rgb = (0.93, 0.93, 0.9) if os.environ.get("BIGGLASS_FRAME") == "white" else (0.05, 0.05, 0.055)
    mname = "ir_bg_frame"
    if os.environ.get("BIGGLASS_FRAME_RGB"):                                 # e.g. 0.30,0.16,0.09 copper-brown (S35); own material name: _flat caches by name
        frame_rgb = tuple(float(x) for x in os.environ["BIGGLASS_FRAME_RGB"].split(",")); mname = "ir_bg_frame_" + "_".join(f"{x:.2f}" for x in frame_rgb)
    frame = fl._flat(mname, frame_rgb, 0.4, 0.5); pane = rs._glass("ir_bg_glass", rough=0.0)
    span = ub - ua; n_m = (3 if span >= 2.4 else 2) if frac < 1.0 else max(2, int(round(span / 2.0))); pitch = span / n_m; hh = z1 - z0      # a partial window is a 3-pane (2 when narrow) clinic window, like the physio ref
    off = -side * 0.02                                                       # frames sit just inside the wall plane
    gaps = _door_gaps(o0, ux, vx, vg, ua, ub) if os.environ.get("BIGGLASS_DOOR_GAPS", "1") != "0" else []
    inside = lambda u: any(g0 - 0.03 <= u <= g1 + 0.03 for g0, g1 in gaps)
    mull = [("box", *at(ua + k * pitch, vg + off), z0 + hh / 2, 0.04, 0.04, hh) for k in range(n_m + 1) if not inside(ua + k * pitch)]
    along_y = abs(at(1, 0)[1] - at(0, 0)[1]) > 0.5                          # the wall may run along world y (a west / east wall: P2b living room): the rail follows it
    for r0, r1 in _spans(ua, ub, gaps, 0.05):                               # the sill rail stops at every door opening; the head rail stays above the door
        rl = r1 - r0; rail_ = (0.07, rl) if along_y else (rl, 0.07); mull += [("box", *at((r0 + r1) / 2, vg + off), z0 + 0.03, *rail_, 0.06)]
    rail = (0.07, span) if along_y else (span, 0.07)
    mull += [("box", *at((ua + ub) / 2, vg + off), z1 - 0.03, *rail, 0.06)]
    fl.mesh_object(name("BigGlassFrame"), [(frame, mull)], bevel=False)
    pq = []
    for k in range(n_m):                                                    # one quad per pitch, minus the door gaps
        for p0, p1 in _spans(ua + k * pitch + 0.03, ua + (k + 1) * pitch - 0.03, gaps, 0.1):
            pq.append(((*at(p0, vg + off), z0 + 0.1), (*at(p1, vg + off), z0 + 0.1), (*at(p1, vg + off), z1 - 0.1), (*at(p0, vg + off), z1 - 0.1)))
    panes_o = rs._quads(name("BigGlassPanes"), pq, pane, thick=rs.GLASS_THICK)
    if frac < 1.0 and os.environ.get("BIGGLASS_FROST", "1") != "0":          # frosted privacy band over the lowest 0.4 m of a partial window (the ref's window has a pale opaque lower band)
        fm = bpy.data.materials.get("ir_bg_frost") or bpy.data.materials.new("ir_bg_frost"); fm.use_nodes = True
        fb = fm.node_tree.nodes["Principled BSDF"]; fb.inputs["Base Color"].default_value = (0.86, 0.88, 0.86, 1); fb.inputs["Roughness"].default_value = 0.6
        rs._quads(name("BigGlassFrost"), [((*at(ua, vg + off * 0.5), z0 + 0.1), (*at(ub, vg + off * 0.5), z0 + 0.1), (*at(ub, vg + off * 0.5), z0 + 0.5), (*at(ua, vg + off * 0.5), z0 + 0.5))], fm)
    cq, cm, gq, grgb = _card(kind, at, L, side, S, (ua + ub) / 2)
    rs._quads(name("BigGlassCard"), [cq], cm)
    gm = bpy.data.materials.get(f"ir_bg_ground_{kind}")
    if gm is None:
        gm = bpy.data.materials.new(f"ir_bg_ground_{kind}"); gm.use_nodes = True; gb = gm.node_tree.nodes["Principled BSDF"]
        gb.inputs["Base Color"].default_value = (*grgb, 1); gb.inputs["Roughness"].default_value = 0.9
    if kind != "skyline":                                                   # a skyline is seen from above the rooftops: the card reaches below the floor, no ground plane
        if os.environ.get("BIGGLASS_FLAT_GROUND") == "1" or not photo_card(kind):
            rs._quads(name("BigGlassGround"), [gq], gm)
        else:                                                               # the ground carries the photo's own road / pavement strip (bottom 16 %), lit like the card, so no flat slab edge shows (S8/S19/S20 review 10-19)
            _photo_ground(name("BigGlassGround"), gq, kind)
    rec = {"room": room, "o0": list(o0), "ux": list(ux), "vx": list(vx), "vg": vg, "ua": ua, "ub": ub, "z0": z0, "z1": z1, "frame": mname, "door": _side_force is not None, "du": _side_force[1] if _side_force else None, "pitch": pitch, "n_m": n_m}
    import json
    if panes_o is not None:
        panes_o["ir_bg_rec"] = json.dumps(rec)                               # the scene property is lost by a stage that rebuilds the scene (mat2); a property on the object travels with it
    old = json.loads(bpy.context.scene.get("ir_bigglass", "[]")); bpy.context.scene["ir_bigglass"] = json.dumps(old + [rec])   # sweep() reads this after the furniture is placed
    hung = drop_hung(rec) + drop_crossers(rec)
    # sun through the glass, 35 deg up, 20 deg off the wall normal
    inward = Vector((*at(0, -side), 0)) - Vector((*at(0, 0), 0)); inward.normalize()
    e, yaw = math.radians(35), math.radians(20)
    dvec = Vector((inward.x * math.cos(yaw) - inward.y * math.sin(yaw), inward.x * math.sin(yaw) + inward.y * math.cos(yaw), 0)) * math.cos(e) + Vector((0, 0, -math.sin(e)))
    ld = bpy.data.lights.new("ir_bg_sun", "SUN"); ld.energy = float(os.environ.get("BIGGLASS_SUN", "0.12" if kind.endswith("_night") else "4.0")); ld.angle = math.radians(0.6); ld.color = (1.0, 0.93, 0.82)
    lo = bpy.data.objects.new(f"SunLampFactory(bigglass).spawn_asset({name('s')})", ld); bpy.context.scene.collection.objects.link(lo)
    lo.rotation_euler = dvec.to_track_quat("-Z", "Y").to_euler(); lo.location = (*at((ua + ub) / 2, vg), zc + 5.0)
    leaf = 0
    if kind not in ("skyline", "street_night") and os.environ.get("BIGGLASS_LEAF", "1") != "0":
        # a leaf gobo 1.2 m outside the wall: visible to shadow rays only, so the sun reaches the floor as dappled tree-shadow (S8/S18 refs: 'leaf-shadow light')
        lm = bpy.data.materials.get("ir_bg_leaf")
        if lm is None:
            lm = bpy.data.materials.new("ir_bg_leaf"); lm.use_nodes = True; N, Lk = lm.node_tree.nodes, lm.node_tree.links; b = N["Principled BSDF"]
            tc = N.new("ShaderNodeTexCoord"); nz = N.new("ShaderNodeTexNoise"); nz.inputs["Scale"].default_value = 14.0; nz.inputs["Detail"].default_value = 5.0
            rp = N.new("ShaderNodeValToRGB"); rp.color_ramp.elements[0].position = 0.50; rp.color_ramp.elements[1].position = 0.57
            rp.color_ramp.elements[0].color = (0, 0, 0, 1); rp.color_ramp.elements[1].color = (1, 1, 1, 1)
            Lk.new(tc.outputs["UV"], nz.inputs["Vector"]); Lk.new(nz.outputs["Fac"], rp.inputs["Fac"]); Lk.new(rp.outputs["Color"], b.inputs["Alpha"]); b.inputs["Base Color"].default_value = (0.05, 0.1, 0.03, 1)
        vo = vg + side * 1.2
        go = rs._quads(name("BigGlassLeaves"), [((*at(ua - 2.0, vo), 0.0), (*at(ub + 2.0, vo), 0.0), (*at(ub + 2.0, vo), z1 + 3.5), (*at(ua - 2.0, vo), z1 + 3.5))], lm)
        go.visible_camera = False; go.visible_glossy = False; go.visible_diffuse = False; go.visible_transmission = False; leaf = 1
    views = bigglass_views(at, L, S, side, zc)
    stats["bigglass"] = {"card": kind, "side": "v=S" if side > 0 else "v=0", "frac": frac, "u": [round(ua, 2), round(ub, 2)], "mullions": n_m + 1, "wall_faces_removed": removed,
                         "windows_removed": gone, "wall_hung_removed": hung, "leaf_gobo": leaf, "wall_patches": patched, "views": views}
    print(f"BIGGLASS {room} card={kind} side={stats['bigglass']['side']} frac={frac} removed={removed} windows={gone}", flush=True)
    return 1


_ARCH = ("BigGlass", "BG")


def _portal(o):
    """The portal cutters ('door', 'door.001', 'window.003' ...) parent every placed door leaf / casing / window: deleting one orphans them at the origin (floor C r16-r18 lost
    5 of 6 doors and 3 of 5 windows through drop_hung, which read the lower-case cutter as a wall-hung item)."""
    return o.name.split(".")[0] in ("door", "window") or any(c.name.startswith("placeholders") for c in o.users_collection) or any(ch.name.startswith(("LiteDoor", "DoorCasing", "Window")) for ch in o.children)


def drop_hung(rec):
    """Delete wall-mounted meshes (a sharps bin, a clock, a poster) in the cut band: centre within 0.35 m of the wall plane and inside the opening's u range, 0.3 m < zmin,
    zmax < 2.4 m and overlapping the opening's height (z0..z1). Architecture (room parts, windows, doors, this kit's own meshes) is kept. Returns the count."""
    import re
    o0, ux, vx = (Vector(rec[k]) for k in ("o0", "ux", "vx")); n = 0
    for o in list(bpy.data.objects):
        if o.type != "MESH" or o.name.startswith(_ARCH) or re.search(r"\.(wall|floor|ceiling|exterior)\b", o.name) or "Window" in o.name or "Door" in o.name or _portal(o):
            continue
        bb = [o.matrix_world @ Vector(c) for c in o.bound_box]; zmin, zmax = min(p.z for p in bb), max(p.z for p in bb); d = sum(bb, Vector()) / 8 - o0
        cv_ = d.dot(vx); inside = (cv_ <= rec["vg"] + 0.05) if rec["vg"] > 0 else (cv_ >= -0.05)               # the room's own side of the glass plane only: an adjacent room's wall item (floors) is not ours
        if inside and abs(cv_ - rec["vg"]) < 0.35 and rec["ua"] < d.dot(ux) < rec["ub"] and 0.3 < zmin and zmax < 2.4 and zmax > rec["z0"] and zmin < rec["z1"]:
            bpy.data.objects.remove(o, do_unlink=True); n += 1
    return n


def drop_crossers(rec):
    """Delete interior kit meshes (track rails, pipes, beams) that stick out through the glass: bbox beyond the wall plane by > 0.15 m, inside the opening's u range."""
    import re
    o0, ux, vx = (Vector(rec[k]) for k in ("o0", "ux", "vx")); sgn = 1.0 if rec["vg"] > 0 else -1.0; n = 0
    for o in list(bpy.data.objects):
        if o.type != "MESH" or o.name.startswith(_ARCH) or re.search(r"\.(wall|floor|ceiling|exterior)\b", o.name) or "Window" in o.name or "Door" in o.name or _portal(o) or o.name.startswith("SunLamp"):
            continue
        bb = [(o.matrix_world @ Vector(c) - o0) for c in o.bound_box]
        out = max(sgn * (p.dot(vx) - rec["vg"]) for p in bb) if rec["vg"] > 0 else max(p.dot(vx) * -1.0 for p in bb)
        us = [p.dot(ux) for p in bb]; cv = sum(p.dot(vx) for p in bb) / 8
        if (cv > rec["vg"]) if rec["vg"] > 0 else (cv < 0):                  # centre beyond the glass plane = another room's furniture (floors): not ours to delete (floor C r16 lost every desk)
            continue
        if out > 0.15 and max(us) > rec["ua"] and min(us) < rec["ub"]:
            bpy.data.objects.remove(o, do_unlink=True); n += 1
    return n


def all_recs():
    """Every recorded glass run: scene['ir_bigglass'], else the 'ir_bg_rec' property of the BigGlassPanes objects (survives the mat2 stage, which drops the scene property)."""
    import json
    recs = json.loads(bpy.context.scene.get("ir_bigglass", "[]"))
    if recs:
        return recs
    return [json.loads(o["ir_bg_rec"]) for o in bpy.data.objects if o.get("ir_bg_rec")]


def sweep():
    """Post-realize: drop_hung for every glass band recorded by apply() (furniture placed after the architecture pass can float in the opening)."""
    import json
    recs = all_recs()
    for r in recs:
        if r.get("door"):
            _door_leaves(r)
    return sum(drop_hung(r) + drop_crossers(r) for r in recs)


def _door_leaves(rec):
    """BIGGLASS_SIDE=door: the flush leaf standing in the glass run takes the frame colour (flush_doors has run by now); the vision panel stays glass."""
    fm = bpy.data.materials.get(rec["frame"])
    o0 = Vector(rec["o0"]); ux = Vector(rec["ux"]); vx = Vector(rec["vx"])
    for o in bpy.data.objects:
        if o.type != "MESH" or not o.name.startswith("LiteDoorFactory") or fm is None:
            continue
        t = (o.parent.matrix_world.translation if o.parent is not None else o.matrix_world.translation) - o0
        if abs(t.dot(vx) - rec["vg"]) < 0.6 and rec["ua"] < t.dot(ux) < rec["ub"]:
            for sl in o.material_slots:
                if sl.material is not None and sl.material.name.startswith("ir_office_door_leaf"):
                    sl.material = fm
