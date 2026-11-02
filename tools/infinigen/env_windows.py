"""A real outside view behind every exterior window (review 10-19: 'windows with NO real outside view', 22 of 23 scenes). Hooked from kit_lighting after
street_backdrop, only when ROOM_ENV_WINDOWS=1; ROOM_ENV_KIND = street (default) | garden | street_night.

    from env_windows import apply; stats["env_windows"] = apply(stats)

For every WindowFactory mesh >= 0.8 m wide whose outward side is outside all room footprints: windows on the same wall line share one card. The card is the
big_glass photo card (emissive, transparent to shadow rays) 16 m outside, and the ground between wall and card carries the photo's own road strip
(big_glass._photo_ground), so no flat ground slab edge shows. Windows already replaced by big_glass (BigGlassCard objects) are skipped by their absence.
"""
from __future__ import annotations

import os
from pathlib import Path

import bpy
from mathutils import Vector

import room_dressing as rd


OUTSIDE = Path("/jarvis/project/robomituba/data/venue_refs/outside_views")
KIND_PREFIX = {"street": ("street_day",), "street_dusk": ("street_dusk",), "street_night": ("street_night",), "winter": ("winter_trees",), "garden": ("garden",),
               "campus": ("campus",), "office": ("office_ct",), "skyline": ("skyline_day",), "skyline_dusk": ("skyline_dusk",), "industrial": ("industrial",), "rooftop": ("rooftop",)}
HORIZON = {"street": 0.27, "street_dusk": 0.25, "street_night": 0.25, "winter": 0.32, "garden": 0.35, "campus": 0.36, "office": 0.34, "skyline": 0.42, "skyline_dusk": 0.40, "industrial": 0.42, "rooftop": 0.38}   # horizon row from the bottom, read off the first generated panoramas (10-19)


def _pick_card(kind):
    """ROOM_ENV_KIND -> (card kind for big_glass._card, horizon). A generated panorama from data/venue_refs/outside_views is chosen with the scene seed (ROOM_ENV_SEED or the .blend
    path); its file is linked as bigglass_cards/src/env_<stem>.png so big_glass.photo_card finds it. No panorama of that kind yet: the old 4 cards (street / garden / skyline / street_night)."""
    import hashlib
    files = sorted(f for p in KIND_PREFIX.get(kind, ()) for f in OUTSIDE.glob(p + "_*.png")) if OUTSIDE.is_dir() else []
    if not files:
        return kind if kind in ("street", "garden", "skyline", "street_night") else "street", None
    seed = os.environ.get("ROOM_ENV_SEED") or bpy.data.filepath or "0"
    f = files[int(hashlib.md5(seed.encode()).hexdigest(), 16) % len(files)]
    if os.environ.get("ROOM_ENV_FILE"):                                        # a named panorama (stem, e.g. campus_03: autumn treetops seen from an upper floor, O2 r23)
        f = next((q for q in OUTSIDE.glob("*.png") if q.stem == os.environ["ROOM_ENV_FILE"]), f)
    from room_planner import big_glass as bg
    link = bg.CARDS / "src" / f"env_{f.stem}.png"
    try:
        if not link.exists():
            link.symlink_to(f)
    except OSError:
        return kind if kind in ("street", "garden", "skyline", "street_night") else "street", None
    return f"env_{f.stem}", float(os.environ.get("ROOM_ENV_HORIZON") or HORIZON.get(kind, 0.30))      # ROOM_ENV_HORIZON=0.62: eye level on a taller part of the photo (P2b r31: 0.42 showed only the water band of skyline_day_01 = grey + dots)


def _strip_slats(o):
    """Replace a slatted / louvred exterior window mesh (thousands of polys; the slats hide the outside card) by its frame, mullions and one glass pane. The object, its name, its parent
    and its children (portal lights) stay; only the mesh data is swapped. Returns True when replaced."""
    import bmesh
    if len(o.data.polygons) < 400:
        return False
    bb = [Vector(c) for c in o.bound_box]
    lo = Vector((min(p.x for p in bb), min(p.y for p in bb), min(p.z for p in bb))); hi = Vector((max(p.x for p in bb), max(p.y for p in bb), max(p.z for p in bb)))
    ext = hi - lo
    axes = sorted(range(3), key=lambda a: ext[a])                  # thin axis first
    thin = axes[0]; wide = [a for a in (0, 1) if a != thin][0] if thin != 2 else 0
    wide = max((a for a in (0, 1, 2) if a != thin and a != 2), key=lambda a: ext[a], default=0)
    tall = 2
    th = max(0.04, min(ext[thin], 0.12)); fw = 0.06
    from room_planner import proc_assets as pa
    fr_m = o.data.materials[0] if o.data.materials and o.data.materials[0] else pa._flat("ir_env_win_frame", (0.2, 0.21, 0.23), 0.4, 0.8)
    gl_m = bpy.data.materials.get("ir_env_win_glass") or pa._flat("ir_env_win_glass", (0.92, 0.94, 0.95), 0.02, transmission=1.0)
    bm = bmesh.new()

    def box(c0, c1, slot):
        r = bmesh.ops.create_cube(bm, size=1.0)
        sc = [c1[i] - c0[i] for i in range(3)]; ce = [(c0[i] + c1[i]) / 2 for i in range(3)]
        bmesh.ops.scale(bm, vec=sc, verts=r["verts"]); bmesh.ops.translate(bm, vec=ce, verts=r["verts"])
        for f in {f for v in r["verts"] for f in v.link_faces}:
            f.material_index = slot

    def vec(w, t, z):
        v = [0, 0, 0]; v[wide] = w; v[thin] = t; v[tall] = z; return v
    mid = (lo[thin] + hi[thin]) / 2
    box(vec(lo[wide], mid - th / 2, lo[tall]), vec(hi[wide], mid + th / 2, lo[tall] + fw), 0)          # sill and head
    box(vec(lo[wide], mid - th / 2, hi[tall] - fw), vec(hi[wide], mid + th / 2, hi[tall]), 0)
    box(vec(lo[wide], mid - th / 2, lo[tall]), vec(lo[wide] + fw, mid + th / 2, hi[tall]), 0)          # jambs
    box(vec(hi[wide] - fw, mid - th / 2, lo[tall]), vec(hi[wide], mid + th / 2, hi[tall]), 0)
    n = max(1, int(round(ext[wide] / 1.4)))
    for k in range(1, n):                                                                                  # mullions
        w = lo[wide] + k * ext[wide] / n
        box(vec(w - 0.02, mid - th / 2, lo[tall]), vec(w + 0.02, mid + th / 2, hi[tall]), 0)
    box(vec(lo[wide] + fw, mid - 0.006, lo[tall] + fw), vec(hi[wide] - fw, mid + 0.006, hi[tall] - fw), 1)  # the glass pane
    me = bpy.data.meshes.new(o.data.name + "_open"); bm.to_mesh(me); bm.free()
    me.materials.append(fr_m); me.materials.append(gl_m)
    o.data = me
    return True


def apply(stats, kind=None):
    if os.environ.get("ROOM_ENV_WINDOWS") != "1":
        return 0
    from room_planner import big_glass as bg
    kind = kind or os.environ.get("ROOM_ENV_KIND") or "street"
    kind0 = kind
    kind, horizon = _pick_card(kind)
    boxes, fz = [], 0.0
    for p_ in rd._rooms().values():
        if "floor" not in p_:
            continue
        pts = [p_["floor"].matrix_world @ Vector(c) for c in p_["floor"].bound_box]
        boxes.append((min(q.x for q in pts), max(q.x for q in pts), min(q.y for q in pts), max(q.y for q in pts)))
        fz = max(fz, max(q.z for q in pts)) if len(boxes) > 1 else max(q.z for q in pts)
    if not boxes:
        return 0
    inside = lambda x, y: any(b[0] - 0.05 <= x <= b[1] + 0.05 and b[2] - 0.05 <= y <= b[3] + 0.05 for b in boxes)
    groups = {}
    for o in bpy.data.objects:
        if o.type != "MESH" or not o.name.startswith("WindowFactory("):
            continue
        wp = [o.matrix_world @ Vector(c_) for c_ in o.bound_box]           # WORLD extents: a window rotated 90 deg for a west / east wall has its length along local x, so o.dimensions
        d = Vector((max(q.x for q in wp) - min(q.x for q in wp), max(q.y for q in wp) - min(q.y for q in wp), 0.0))   # called every window 'along x' and the x-wall windows never got a card (floor O r5)
        along_x = d.x >= d.y; W = max(d.x, d.y)
        if W < 0.8:
            continue
        c = o.matrix_world.translation
        n = None
        for s in (1, -1):
            nv = Vector((0, s, 0)) if along_x else Vector((s, 0, 0))
            if not inside(c.x + nv.x * 1.5, c.y + nv.y * 1.5) and inside(c.x - nv.x * 1.5, c.y - nv.y * 1.5):
                n = nv; break
        if n is None:                                            # an interior window (between rooms) or a free-standing one
            continue
        if os.environ.get("ROOM_ENV_STRIP_SLATS", "1") != "0" and _strip_slats(o):
            stats["env_window_slats_stripped"] = stats.get("env_window_slats_stripped", 0) + 1
        t = Vector((1, 0, 0)) if along_x else Vector((0, 1, 0))
        wall = (c.y if along_x else c.x)
        key = (along_x, int(n.x + n.y), round(wall, 1))
        u = c.x if along_x else c.y
        g = groups.setdefault(key, {"n": n, "t": t, "wall": wall, "u": []})
        g["u"].append(u)
    made = 0
    for i, (key, g) in enumerate(groups.items()):
        n, t = g["n"], g["t"]; u0 = sum(g["u"]) / len(g["u"])
        o0 = Vector((u0, g["wall"], 0)) if key[0] else Vector((g["wall"], u0, 0))
        at = lambda u, v, o0=o0, t=t, n=n: (o0.x + t.x * u + n.x * v, o0.y + t.y * u + n.y * v)
        if horizon is not None:                                  # big_glass._card reads BIGGLASS_HORIZON for a card kind it has no table entry for
            os.environ["BIGGLASS_HORIZON"] = str(horizon)
        _sv = {k: os.environ.get(k) for k in ("BIGGLASS_CARD_CONTRAST", "BIGGLASS_CARD_EMIT")}
        for _k, _e in (("BIGGLASS_CARD_CONTRAST", "ROOM_ENV_CONTRAST"), ("BIGGLASS_CARD_EMIT", "ROOM_ENV_EMIT")):       # window cards get their own contrast / emission (P2b r32: the terrace's BIGGLASS_CARD_CONTRAST=0.4 made the day skyline facades black silhouettes)
            if os.environ.get(_e) is not None:
                os.environ[_k] = os.environ[_e]
        try:
            cq, cm, gq, grgb = bg._card(kind, at, 0.0, 1, 0.0, 0.0)
        finally:
            for _k, _v in _sv.items():
                if _v is None:
                    os.environ.pop(_k, None)
                else:
                    os.environ[_k] = _v
        lift = lambda q, dz=0.0: tuple((x, y, z + fz + dz) for x, y, z in q)
        bg.rs._quads(f"EnvWindowCard_{i}", [lift(cq)], cm)
        if kind != "skyline" and not kind0.startswith("skyline") and not kind.startswith("env_skyline"):      # a skyline is seen from above: the card reaches below the floor, no ground slab (floor C r23: a rippled slab with a hard edge)
            if bg.photo_card(kind):
                bg._photo_ground(f"EnvWindowGround_{i}", lift(gq, -0.001 * i), kind)
            else:
                gm = bpy.data.materials.get(f"ir_bg_ground_{kind}") or bpy.data.materials.new(f"ir_bg_ground_{kind}")
                bg.rs._quads(f"EnvWindowGround_{i}", [lift(gq, -0.001 * i)], gm)
        made += 1
    if horizon is not None:
        os.environ.pop("BIGGLASS_HORIZON", None)
    stats["env_window_groups"] = made; stats["env_card"] = kind
    return made
