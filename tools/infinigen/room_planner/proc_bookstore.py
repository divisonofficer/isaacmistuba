"""Underground-bookstore props (design proposal docs/bookstore_underground_design_proposal.md): book islands, tall wall shelving, section signs.

Factory-shaped like proc_assets (Cls(seed).spawn_asset(i), front +X, origin at the bottom; the wall shelf has its back at x = 0). Books are
12-triangle boxes whose UVs point into a synthetic cover atlas (gen_book_covers.py), one mesh per island / shelf bay, ONE atlas material per
object -- ~450 books per island, ~540 per wall shelf. Optional HSSD book models (hssd_n) are parented on top of an island when the HSSD index
is loaded (ROOM_EXTRA_ASSET_INDEXES); without it they are skipped.

Book modes (box dims in the book's own frame, x forward / y width-of-row / z up):
  spine_out  dims (cover width, thickness, height): spine faces +X, covers on +-Y      (standing on a shelf, spine to the aisle)
  flat       dims (height, width, thickness):      cover on +Z (image up = +X), spine on -Y (lying in a pile)
  face_out   dims (thickness, width, height):      cover on +X, spine on -Y            (cover facing the aisle)
"""
from __future__ import annotations

import json
import math
import random
from pathlib import Path

import bmesh
import bpy
from mathutils import Matrix, Vector

ATLAS_DIR = Path("/jarvis/project/robomituba/data/venue_refs/book_atlas")
SIGN_DIR = Path("/jarvis/project/robomituba/data/venue_refs/book_signs")
_META: dict | None = None


def _pa():
    from room_planner import proc_assets
    return proc_assets


def meta() -> dict:
    global _META
    if _META is None:
        _META = json.loads((ATLAS_DIR / "atlas_meta.json").read_text())
    return _META


ROLES = {"spine_out": {(0, 1, 0): "cover", (0, -1, 0): "cover", (1, 0, 0): "spine"},
         "flat": {(0, 0, 1): "cover", (0, -1, 0): "spine"},
         "face_out": {(1, 0, 0): "cover", (0, -1, 0): "spine"}}


def _tile_rect(kind: str, idx: int):
    """(u0, v0, u1, v1) of a tile in the atlas, v up (Blender), 3 px inset against bleeding."""
    m = meta(); W, H = m["atlas_w"], m["atlas_h"]
    if kind == "cover":
        cw, ch = m["cover"]; x, y = (idx % m["cols"]) * cw, (idx // m["cols"]) * ch
    elif kind == "spine":
        x, y, cw, ch = (idx % m["n_spines"]) * m["spine_w"], m["rows"] * m["cover"][1], m["spine_w"], m["cover"][1]
    else:
        x, y, cw, ch = m["cream_tile"]
    p = 3
    return ((x + p) / W, 1 - (y + ch - p) / H, (x + cw - p) / W, 1 - (y + p) / H)


def add_book(bm, uvl, center, dims, mode, cover_idx, yaw=0.0, lean=0.0, lean_side=1):
    """One box book. `cover_idx` picks the cover tile; its spine tile is cover_idx % n_spines."""
    m = meta(); roles = ROLES[mode]
    r = bmesh.ops.create_cube(bm, size=1.0)
    bmesh.ops.scale(bm, vec=dims, verts=r["verts"])
    for f in {f for v in r["verts"] for f in v.link_faces}:
        n = tuple(round(c) for c in f.normal)
        role = roles.get(n)
        if role is None:                                      # page edges / back cover: the plain cream tile
            u0, v0, u1, v1 = _tile_rect("cream", 0)
            for lp in f.loops:
                lp[uvl].uv = ((u0 + u1) / 2, (v0 + v1) / 2)
            continue
        idx = cover_idx if role == "cover" else cover_idx % m["n_spines"]
        u0, v0, u1, v1 = _tile_rect(role, idx)
        up = Vector((1, 0, 0)) if (n == (0, 0, 1) or (mode == "flat" and role == "spine")) else Vector((0, 0, 1))
        fwd = -Vector(n); right = fwd.cross(up)
        for lp in f.loops:
            c = lp.vert.co
            su = abs(right.x) * dims[0] + abs(right.y) * dims[1] + abs(right.z) * dims[2]
            sv = abs(up.x) * dims[0] + abs(up.y) * dims[1] + abs(up.z) * dims[2]
            u = 0.5 + c.dot(right) / su; v = 0.5 + c.dot(up) / sv
            lp[uvl].uv = (u0 + (u1 - u0) * u, v0 + (v1 - v0) * v)
    if lean:                                              # a standing book leaning toward `lean_side` (+-1 along y): pivots on its lower edge on that side (S24: messy shelves)
        bmesh.ops.rotate(bm, cent=(0, lean_side * dims[1] / 2, -dims[2] / 2), matrix=Matrix.Rotation(-lean_side * lean, 3, "X"), verts=r["verts"])
    if yaw:
        bmesh.ops.rotate(bm, cent=(0, 0, 0), matrix=Matrix.Rotation(yaw, 3, "Z"), verts=r["verts"])
    bmesh.ops.translate(bm, vec=tuple(center), verts=r["verts"])
    return r["verts"]


def atlas_material(k: int):
    name = f"ir_book_atlas_{k}"
    m = bpy.data.materials.get(name)
    if m is not None:
        return m
    m = bpy.data.materials.new(name); m.use_nodes = True
    nt = m.node_tree; b = nt.nodes["Principled BSDF"]
    t = nt.nodes.new("ShaderNodeTexImage"); t.image = bpy.data.images.load(str(ATLAS_DIR / f"atlas_{k}.png"), check_existing=True)
    t.interpolation = "Linear"; nt.links.new(t.outputs["Color"], b.inputs["Base Color"])
    b.inputs["Roughness"].default_value = 0.5
    return m


def _object(name, groups, books_bm=None, books_mat=None, bevel=True):
    """Furniture boxes (groups, as proc_assets._parts_object) plus the book mesh joined into one object."""
    pa = _pa()
    if books_bm is not None:
        me = bpy.data.meshes.new(name + "_books"); books_bm.to_mesh(me); books_bm.free()
        me.materials.append(books_mat)
        bo = bpy.data.objects.new(name + "_books", me); bpy.context.scene.collection.objects.link(bo)
    base = pa._parts_object(name, groups)
    if books_bm is not None:
        base.data.materials.append(books_mat)
        bpy.ops.object.select_all(action="DESELECT")
        for o in (base, bo):
            o.select_set(True)
        bpy.context.view_layer.objects.active = base
        bpy.ops.object.join()
        base = bpy.context.view_layer.objects.active
        base.name = name
    return base


def _row(bm, uvl, rng, x_front, y0, y1, z0, side, k_cover_start=0, depth=(0.12, 0.19), height=(0.17, 0.26), thick=(0.018, 0.045), cover=None):
    """Spine-out books along y from y0 to y1 on a board whose top is z0, flush to the shelf's front edge `x_front`, spine toward `side` (+1 -> +X).
    Messy like the reference (S24 r5 review): gaps with a neighbour leaning into them, a few books canted, a flat book lying across the tops of a run, and a short flat stack at the row's end."""
    y, n = y0, 0
    lean_next, recent = False, []
    pick = lambda: rng.randrange(meta()["n_covers"]) if cover is None else cover
    while y < y1 - 0.02:
        t = rng.uniform(*thick); h = rng.uniform(*height); d = rng.uniform(*depth)
        if y + t > y1:
            break
        if rng.random() > 0.05:                               # a gap now and then
            lean, ls = 0.0, rng.choice((-1, 1))
            if lean_next:                                     # the book beside a gap leans into it (the gap lies at lower y)
                lean, ls, lean_next = rng.uniform(0.2, 0.45), -1, False
            elif rng.random() < 0.06:                         # a few canted books
                lean = rng.uniform(0.05, 0.14)
            add_book(bm, bm.loops.layers.uv.active, (x_front - side * d / 2, y + t / 2, z0 + h / 2 + 0.002), (d, t, h), "spine_out", pick(),
                     yaw=0.0 if side > 0 else math.pi, lean=lean, lean_side=ls)
            recent.append((y, y + t, h)); recent = recent[-4:]
            n += 1
        else:
            lean_next = rng.random() < 0.7; y += rng.uniform(0.03, 0.08)
        if len(recent) == 4 and rng.random() < 0.025:          # a flat book lying across the tops of the last four
            hmax = max(q[2] for q in recent); w = rng.uniform(0.13, 0.17); hh = rng.uniform(0.17, 0.24); tt = rng.uniform(0.02, 0.04)
            add_book(bm, bm.loops.layers.uv.active, (x_front - side * hh / 2, (recent[0][0] + recent[-1][1]) / 2, z0 + hmax + tt / 2 + 0.003), (hh, w, tt), "flat", pick(),
                     yaw=(0.0 if side > 0 else math.pi) + rng.uniform(-0.5, 0.5))
            n += 1; recent = []
        y += t + rng.uniform(0.0, 0.004)
    room = y1 - y
    if room > 0.22 and rng.random() < 0.4:                    # a short lying stack where the standing books stop
        zz = z0 + 0.002; cy = y + room / 2
        for _ in range(rng.randint(2, 5)):
            tt = rng.uniform(0.02, 0.045); hh = rng.uniform(0.15, 0.24); w = rng.uniform(0.11, 0.17)
            add_book(bm, bm.loops.layers.uv.active, (x_front - side * hh / 2 - rng.uniform(0.0, 0.03), cy + rng.uniform(-0.025, 0.025), zz + tt / 2), (hh, w, tt), "flat", pick(),
                     yaw=(0.0 if side > 0 else math.pi) + rng.uniform(-0.3, 0.3))
            zz += tt; n += 1
    return n


class BookIslandTableFactory:
    """Two-sided display island (front +X): grey laminate top 2.0-2.8 x 0.9-1.1 m at 0.84 m on a charcoal body with two open shelf levels per
    side, spine-out books on the shelves, flat piles on the top. ~450 books, ~6k triangles."""
    def __init__(self, seed, hssd_n=0):
        r = random.Random(seed)
        self.L = r.choice((2.0, 2.4, 2.8)); self.D = r.choice((0.9, 1.0, 1.1)); self.H = 0.84
        self.atlas = r.randrange(meta()["n_atlases"]); self.seed = seed; self.hssd_n = hssd_n
        self.focus = None                                      # a bestseller table sets one cover tile for every copy

    def spawn_asset(self, i):
        pa = _pa(); r = random.Random(self.seed * 13 + i); L, D, H = self.L, self.D, self.H
        top = pa._flat("ir_book_top", (0.66, 0.67, 0.68), 0.45)
        body = pa._flat("ir_book_cabinet_body", (0.13, 0.14, 0.15), 0.6)
        parts_body = [(0, 0, 0.04, D - 0.04, L - 0.04, 0.08)]                               # plinth
        parts_body += [(0, s * (L / 2 - 0.015), (H - 0.04) / 2 + 0.04, D, 0.03, H - 0.08) for s in (1, -1)]    # end panels
        parts_body += [(0, 0, (H - 0.04) / 2 + 0.04, 0.025, L - 0.06, H - 0.08)]                              # centre partition
        for s in (1, -1):                                                                    # shelf boards + a low book stop
            for zb in (0.12, 0.40):
                parts_body += [(s * (D / 4 + 0.0125), 0, zb, D / 2 - 0.03, L - 0.06, 0.02), (s * (D / 2 - 0.02), 0, zb + 0.02, 0.012, L - 0.06, 0.03)]
        bm = bmesh.new(); bm.loops.layers.uv.verify(); uvl = bm.loops.layers.uv.active
        n = 0
        for s in (1, -1):
            for zb in (0.12, 0.40):
                n += _row(bm, uvl, r, s * (D / 2 - 0.045), -L / 2 + 0.05, L / 2 - 0.05, zb + 0.01, s, depth=(0.12, min(0.19, D / 2 - 0.08)), cover=self.focus)
        zt = H                                                                               # piles on the top slab
        nx, ny = 3, int((L - 0.2) / 0.28)
        for a in range(nx):
            for b in range(ny):
                cx = (a - (nx - 1) / 2) * 0.3; cy = -L / 2 + 0.2 + (b + 0.5) * (L - 0.4) / ny
                z = zt + 0.002
                sx_, sy_ = 0.0, 0.0                                                      # a pile drifts as it grows: slid, uneven, different sizes (S24 review: 'lie down far too tidily')
                for _ in range(r.randint(3, 9)):
                    t = r.uniform(0.015, 0.05); hh = r.uniform(0.15, 0.3); w = r.uniform(0.11, 0.22)
                    sx_ += r.uniform(-0.02, 0.02); sy_ += r.uniform(-0.02, 0.02)
                    add_book(bm, uvl, (cx + r.uniform(-0.03, 0.03) + sx_, cy + r.uniform(-0.03, 0.03) + sy_, z + t / 2), (hh, w, t), "flat",
                             r.randrange(meta()["n_covers"]) if self.focus is None else self.focus, yaw=r.choice((-1, 1)) * r.uniform(0.17, 0.44) if r.random() < 0.7 else r.uniform(-0.1, 0.1))
                    z += t; n += 1
        o = _object(f"BookIslandTableFactory({self.seed}).spawn_asset({i})", [(body, parts_body), (top, [(0, 0, H - 0.02, D, L, 0.04)])],
                    bm, atlas_material(self.atlas))
        o["book_count"] = n
        if self.hssd_n:
            self._hssd_books(o, r, zt)
        return o

    def _hssd_books(self, island, rng, zt):
        """A few HSSD book models standing face-out on the top slab (only when the HSSD index is loaded)."""
        try:
            import abo_assets as abo
            pool = [e for e in abo.entries() if e.get("source") == "hssd" and e.get("hssd_category") == "book" and e["triangles"] <= 4000]
            for k in range(self.hssd_n if pool else 0):
                e = rng.choice(pool); b = abo._import(e, f"HssdBook({e['id']})")
                b.parent = island; b.location = (rng.uniform(-0.3, 0.3), rng.uniform(-self.L / 2 + 0.2, self.L / 2 - 0.2), zt + 0.002)
                b.rotation_euler = (0, 0, rng.uniform(-0.3, 0.3))
        except Exception as ex:                               # noqa: BLE001 -- optional extra, never fail the island
            island["hssd_books_error"] = str(ex)[:80]


class BookWallShelfFactory:
    """Tall dark wall shelving (front +X, back at x = 0): 2.4 m wide x 0.35 deep x 2.4 m high, 7 levels of spine-out books, ~540 books."""
    def __init__(self, seed):
        self.atlas = random.Random(seed).randrange(meta()["n_atlases"]); self.seed = seed

    def spawn_asset(self, i):
        pa = _pa(); r = random.Random(self.seed * 17 + i); W, D, Hh = 2.4, 0.35, 2.4
        frame = pa._flat("ir_book_wallshelf", (0.17, 0.18, 0.19), 0.55)
        parts = [(0.01, 0, Hh / 2, 0.02, W, Hh)]                                             # back panel
        parts += [(D / 2, s * (W / 2 - 0.015), Hh / 2, D, 0.03, Hh) for s in (1, -1)]
        parts += [(D / 2, 0, 0.05, D, W, 0.1)]                                               # toe kick
        levels = [0.1 + k * 0.33 for k in range(7)]
        parts += [(D / 2, 0, z, D, W - 0.06, 0.022) for z in levels] + [(D / 2, 0, Hh - 0.011, D, W, 0.022)]
        bm = bmesh.new(); bm.loops.layers.uv.verify(); uvl = bm.loops.layers.uv.active; n = 0
        for z in levels:
            n += _row(bm, uvl, r, D - 0.04, -W / 2 + 0.05, W / 2 - 0.05, z + 0.011, 1, height=(0.18, 0.29), depth=(0.13, 0.22))
        o = _object(f"BookWallShelfFactory({self.seed}).spawn_asset({i})", [(frame, parts)], bm, atlas_material(self.atlas))
        o["book_count"] = n
        return o


class SectionSignFactory:
    """Section sign on a pole (front +X): a black plate 0.36 x 0.28 m with a code ('C11') and a label, on a 1.1 m pole and a floor plate."""
    CODES = ("A1", "B13", "C1", "C3", "C10", "C11", "D2", "E1", "소설", "에세이", "만화", "잡화", "참고서", "어린이", "베스트셀러")   # + Korean section names (S24 r4 note)

    def __init__(self, seed):
        self.code = random.Random(seed).choice(self.CODES); self.seed = seed

    def spawn_asset(self, i):
        pa = _pa()
        steel = pa._flat("ir_sign_steel", (0.1, 0.1, 0.11), 0.45, 0.8)
        o = pa._parts_object(f"SectionSignFactory({self.seed}).spawn_asset({i})",
                             [(steel, [(0, 0, 0.008, 0.26, 0.26, 0.016), (0, 0, 0.55, 0.02, 0.02, 1.1), (0, 0, 1.15, 0.025, 0.37, 0.29)])])
        img = SIGN_DIR / f"sign_{self.code}.png"
        if img.exists():                                                                      # the printed face, a thin plane in front of the plate
            m = bpy.data.materials.get(f"ir_sign_face_{self.code}") or bpy.data.materials.new(f"ir_sign_face_{self.code}")
            if not m.use_nodes or "Image Texture" not in [n.name for n in m.node_tree.nodes]:
                m.use_nodes = True; nt = m.node_tree; b = nt.nodes["Principled BSDF"]
                t = nt.nodes.new("ShaderNodeTexImage"); t.image = bpy.data.images.load(str(img), check_existing=True)
                nt.links.new(t.outputs["Color"], b.inputs["Base Color"]); b.inputs["Roughness"].default_value = 0.4
            me = bpy.data.meshes.new("sign_face"); bm = bmesh.new(); uv = bm.loops.layers.uv.verify()
            vs = [bm.verts.new((0.0135, y, 1.15 + z)) for y, z in ((-0.17, -0.135), (0.17, -0.135), (0.17, 0.135), (-0.17, 0.135))]
            f = bm.faces.new(vs)
            for lp, uvc in zip(f.loops, ((0, 0), (1, 0), (1, 1), (0, 1))):
                lp[uv].uv = uvc
            bm.to_mesh(me); bm.free(); me.materials.append(m)
            fo = bpy.data.objects.new("sign_face", me); bpy.context.scene.collection.objects.link(fo)
            bpy.ops.object.select_all(action="DESELECT"); o.select_set(True); fo.select_set(True)
            bpy.context.view_layer.objects.active = o; bpy.ops.object.join()
            o = bpy.context.view_layer.objects.active
        return o


class PopStandFactory:
    """Promotion floor stand (bookstore VLM: 'POP signs and props are thin'): a 0.5 x 0.6 x 1.55 m 3-tier cardboard-style display with face-out books on every tier and a tall
    colourful header board (3 colours by seed) on top. One mesh, atlas covers."""
    def __init__(self, seed):
        r = random.Random(seed); self.atlas = r.randrange(meta()["n_atlases"]); self.seed = seed
        self.c = r.choice(((0.9, 0.25, 0.2), (0.15, 0.45, 0.75), (0.95, 0.75, 0.15)))

    def spawn_asset(self, i):
        pa = _pa(); r = random.Random(self.seed * 53 + i)
        body = pa._flat("ir_pop_body", (0.85, 0.82, 0.76), 0.7); head = pa._flat(f"ir_pop_head_{int(self.c[0] * 100)}_{int(self.c[1] * 100)}", self.c, 0.5)
        parts = [(-0.2, 0.0, 0.78, 0.04, 0.6, 1.56)] + [(0.0, 0.0, 0.1 + k * 0.45, 0.5, 0.6, 0.03) for k in range(3)]
        bm = bmesh.new(); bm.loops.layers.uv.verify(); uvl = bm.loops.layers.uv.active
        n = 0
        for k in range(3):
            for q in range(4):
                add_book(bm, uvl, (0.12 + r.uniform(-0.01, 0.01), -0.22 + q * 0.145, 0.1 + k * 0.45 + 0.17 + 0.015), (0.03, 0.125, 0.19 + r.uniform(-0.01, 0.02)), "face_out", r.randrange(meta()["n_covers"]), yaw=r.uniform(-0.06, 0.06))
                n += 1
        o = _object(f"PopStandFactory({self.seed}).spawn_asset({i})", [(body, parts), (head, [(-0.18, 0, 1.5, 0.04, 0.62, 0.3)])], bm, atlas_material(self.atlas))
        o["book_count"] = n
        return o


class BestsellerTableFactory(BookIslandTableFactory):
    """The bestseller display (S24 r4: 'one type of book gathered, with a sign'): the same island, every copy on it one cover; flat piles on top, face-spine rows below."""
    def __init__(self, seed, hssd_n=0):
        super().__init__(seed, hssd_n)
        self.focus = random.Random(seed * 7 + 3).randrange(meta()["n_covers"])


class BestsellerSignFactory(SectionSignFactory):
    CODES = ("베스트셀러",)


POSTER_DIR = Path("/jarvis/project/robomituba/data/venue_refs/book_posters")


class WallPosterFactory:
    """A framed ad poster for the wall (front +X, back at x = 0): a 0.8 x 1.14 m printed sheet in a thin black frame (origin at the bottom; hang it with a lift)."""
    def __init__(self, seed):
        self.seed = seed; files = sorted(POSTER_DIR.glob("poster_*.png")); self.img = files[random.Random(seed).randrange(len(files))] if files else None

    def spawn_asset(self, i):
        pa = _pa(); frame = pa._flat("ir_poster_frame", (0.05, 0.05, 0.055), 0.45, 0.6)
        W, H = 0.8, 1.14
        o = pa._parts_object(f"WallPosterFactory({self.seed}).spawn_asset({i})",
                             [(frame, [(0.012, 0, 0.012, 0.024, W + 0.06, 0.03), (0.012, 0, H + 0.012, 0.024, W + 0.06, 0.03),
                                       (0.012, -(W / 2 + 0.015), H / 2 + 0.012, 0.024, 0.03, H), (0.012, W / 2 + 0.015, H / 2 + 0.012, 0.024, 0.03, H)])])
        if self.img is not None:
            m = bpy.data.materials.get(f"ir_poster_{self.img.stem}") or bpy.data.materials.new(f"ir_poster_{self.img.stem}")
            if not m.use_nodes or "Image Texture" not in [n.name for n in m.node_tree.nodes]:
                m.use_nodes = True; nt = m.node_tree; b = nt.nodes["Principled BSDF"]
                t = nt.nodes.new("ShaderNodeTexImage"); t.image = bpy.data.images.load(str(self.img), check_existing=True)
                nt.links.new(t.outputs["Color"], b.inputs["Base Color"]); b.inputs["Roughness"].default_value = 0.5
            me = bpy.data.meshes.new("poster_face"); bm = bmesh.new(); uv = bm.loops.layers.uv.verify()
            f = bm.faces.new([bm.verts.new((0.026, y, z)) for y, z in ((-W / 2, 0.027), (W / 2, 0.027), (W / 2, 0.027 + H - 0.03), (-W / 2, 0.027 + H - 0.03))])
            for lp, uvc in zip(f.loops, ((0, 0), (1, 0), (1, 1), (0, 1))):
                lp[uv].uv = uvc
            bm.to_mesh(me); bm.free(); me.materials.append(m)
            fo = bpy.data.objects.new("poster_face", me); bpy.context.scene.collection.objects.link(fo)
            bpy.ops.object.select_all(action="DESELECT"); o.select_set(True); fo.select_set(True)
            bpy.context.view_layer.objects.active = o; bpy.ops.object.join()
            o = bpy.context.view_layer.objects.active
        return o
