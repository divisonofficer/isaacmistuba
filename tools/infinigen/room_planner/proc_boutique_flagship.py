"""Props for the large flagship boutique (reference set boutique_large_flagship_01, 2026-10-17). Factory-shaped like proc_assets:
Cls(seed).spawn_asset(i), front +X, origin at the bottom centre (wall items: back at x = 0, origin at the bottom, mount z by the caller).

  StoneSlabTableFactory     tables built from stacked rough-cut limestone slabs (hero object of the reference): 3 blocks x ~12 layers
  WallRailFlatFactory       wall-mounted flat-bar garment rail on brackets (mount at ~1.65 m)
  SteelLatticeScreenFactory a free-standing rusted steel grid with dark shaggy fabric swatches

Poly budget: table ~0.4k tris, rail ~0.1k, screen ~5.5k (3 layers per swatch). `mesh_object` builds one mesh per object (boxes and cylinders in one pass).
`stone` is a scan kind the library lacks: concrete scans stand in for it until a stone scan exists (registered on proc_assets.SCANS).
"""
from __future__ import annotations

import math
import os
import random

import bmesh
import bpy
from mathutils import Matrix, Vector


def _pa():
    from room_planner import proc_assets
    return proc_assets


def mesh_object(name, groups, bevel=True):
    """One object, one slot per group: groups = [(material, [prim, ...])], prim = ("box", cx, cy, cz, sx, sy, sz[, yaw]) or
    ("cyl", (x0, y0, z0), (x1, y1, z1), radius, segments)."""
    pa = _pa()
    bm = bmesh.new(); bm.loops.layers.uv.verify()
    for slot, (mat, prims) in enumerate(groups):
        for p in prims:
            if p[0] == "box":
                _, cx, cy, cz, sx, sy, sz, *yaw = p
                r = bmesh.ops.create_cube(bm, size=1.0, calc_uvs=True)
                bmesh.ops.scale(bm, vec=(sx, sy, sz), verts=r["verts"]); pa._face_uvs(bm, r["verts"])
                if yaw and yaw[0]:
                    bmesh.ops.rotate(bm, cent=(0, 0, 0), matrix=Matrix.Rotation(yaw[0], 3, "Z"), verts=r["verts"])
                mid = (cx, cy, cz)
            elif p[0] == "jbox":                                   # a rough-cut block: every corner moved a little, sometimes a chipped top corner
                _, cx, cy, cz, sx, sy, sz, jit, chip, seed = p
                jr = random.Random(seed)
                r = bmesh.ops.create_cube(bm, size=1.0, calc_uvs=True)
                bmesh.ops.scale(bm, vec=(sx, sy, sz), verts=r["verts"]); pa._face_uvs(bm, r["verts"])
                top = [v for v in r["verts"] if v.co.z > 0]
                for v in r["verts"]:
                    v.co.x += jr.uniform(-jit, jit); v.co.y += jr.uniform(-jit, jit); v.co.z += jr.uniform(-jit, jit) * 0.15
                if jr.random() < chip and top:                     # bevel chip: one top corner knocked down and in
                    v = jr.choice(top); v.co.z -= jr.uniform(0.012, 0.032); v.co.x -= math.copysign(jr.uniform(0.008, 0.02), v.co.x); v.co.y -= math.copysign(jr.uniform(0.008, 0.02), v.co.y)
                mid = (cx, cy, cz)
            elif p[0] == "tap":                                    # ("tap", cx, cy, zc, h, r_top, r_bot, y_scale, yaw): a flattened frustum (a garment body that tapers smoothly instead of stepping)
                _, cx_, cy_, cz_, h_, rt_, rb_, ys_, yw_ = p
                r = bmesh.ops.create_cone(bm, cap_ends=True, segments=14, radius1=rb_, radius2=rt_, depth=h_, calc_uvs=True)
                bmesh.ops.scale(bm, vec=(1.0, ys_, 1.0), verts=r["verts"])
                if yw_:
                    bmesh.ops.rotate(bm, cent=(0, 0, 0), matrix=Matrix.Rotation(yw_, 3, "Z"), verts=r["verts"])
                mid = (cx_, cy_, cz_)
            elif p[0] == "sph":                                    # ("sph", (x, y, z), radius, subdivisions): an icosphere
                _, c0, rad, sub = p
                r = bmesh.ops.create_icosphere(bm, subdivisions=sub, radius=rad, calc_uvs=True)
                mid = Vector(c0)
            else:
                _, p0, p1, rad, n = p
                v = Vector(p1) - Vector(p0)
                r = bmesh.ops.create_cone(bm, cap_ends=True, segments=n, radius1=rad, radius2=rad, depth=v.length, calc_uvs=True)
                bmesh.ops.rotate(bm, cent=(0, 0, 0), matrix=Vector((0, 0, 1)).rotation_difference(v.normalized()).to_matrix(), verts=r["verts"])
                mid = (Vector(p0) + Vector(p1)) / 2
            bmesh.ops.translate(bm, vec=tuple(mid), verts=r["verts"])
            for f in {f for vv in r["verts"] for f in vv.link_faces}:
                f.material_index = slot
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    for mat, _ in groups:
        me.materials.append(mat)
    o = bpy.data.objects.new(name, me)
    bpy.context.scene.collection.objects.link(o)
    if bevel:
        pa._bevel(o)
    return o


def _flat(name, rgb, rough, metallic=0.0, kind=None, wood=False):
    """proc_assets._flat; `kind` is passed only where _flat takes it (material_spec wired), else the legacy name rules apply."""
    pa = _pa()
    pa.SCANS.setdefault("stone", (pa._TC + "concrete_0003", pa._TC + "concrete_0004"))
    pa.SCAN_TILE.setdefault("stone", 0.6)
    if kind:
        try:
            return pa._flat(name, rgb, rough, metallic, 0.0, wood, kind=kind)
        except TypeError:
            pass
    return pa._flat(name, rgb, rough, metallic, 0.0, wood)


#: stock (flagship r7: 'wall rails bare, stone tables empty'): cheap box garments and folded stacks, one material per colour. Off with ROOM_FLAGSHIP_STOCK=0.
STOCK = os.environ.get("ROOM_FLAGSHIP_STOCK", "1") != "0"
PALETTE = {"camel": (0.55, 0.4, 0.25), "olive": (0.3, 0.33, 0.2), "charcoal": (0.12, 0.12, 0.13), "denim": (0.15, 0.22, 0.38),
           "cream": (0.8, 0.75, 0.65), "rust": (0.5, 0.2, 0.1), "denim_light": (0.3, 0.4, 0.55), "black": (0.05, 0.05, 0.055)}


def _stock_mats():
    return {k: _flat(f"ir_gar_fabric_{k}", c, 0.85) for k, c in PALETTE.items()}


def _hung_garment(rng, y, mats, out, hang):
    """One garment hanging from a rail bar (z = 0 is the bar): turned ~35 deg so the front shows; body + shoulder line + two sleeves + hanger."""
    yaw = rng.uniform(0.45, 0.7) * rng.choice((1, -1)); h = rng.uniform(0.6, 0.95); w = rng.uniform(0.38, 0.46); t = rng.uniform(0.05, 0.08)
    c = rng.choice(("camel", "olive", "charcoal", "denim", "cream", "rust", "denim_light", "black"))
    x = 0.16 + rng.uniform(-0.01, 0.01); dz = -0.06 - h / 2
    sn, cs = math.sin(yaw), math.cos(yaw)
    parts = out.setdefault(c, [])
    parts.append(("box", x, y, dz, t, w, h, yaw))
    parts.append(("box", x, y, -0.07, t * 1.15, w * 1.02, 0.05, yaw))
    for sgn in (1, -1):
        dy = sgn * (w / 2 + 0.015)
        parts.append(("box", x - dy * sn, y + dy * cs, -0.06 - 0.2, 0.05, 0.09, 0.4, yaw + sgn * 0.12))
    hang.append(("box", x, y, -0.025, 0.012, 0.4, 0.012, yaw))


def _folded_stacks(rng, cx0, cy0, w_top, l_top, z_top, mats, out):
    """Stacks of folded knit / denim on a table top (a 2 x n grid, 5-9 layers each)."""
    n = max(2, int((l_top - 0.4) / 0.5)); rows = 2 if w_top > 0.9 else 1
    for a in range(rows):
        for b in range(n):
            if rng.random() < 0.3:
                continue
            cols = [rng.choice(("denim", "denim_light", "camel", "cream", "charcoal", "olive", "rust")) for _ in range(2)]   # two colours alternate by layer: reads as folded garments, not one solid box
            x = cx0 + ((a - (rows - 1) / 2) * 0.34 if rows > 1 else 0.0) + rng.uniform(-0.02, 0.02)
            y = cy0 - l_top / 2 + 0.3 + b * (l_top - 0.6) / max(1, n - 1) + rng.uniform(-0.02, 0.02)
            yaw = rng.uniform(-0.08, 0.08); z = z_top
            for li in range(rng.randint(2, 5)):
                c = cols[li % 2]; th = rng.uniform(0.032, 0.05)
                out.setdefault(c, []).append(("box", x + rng.uniform(-0.006, 0.006), y + rng.uniform(-0.006, 0.006), z + th / 2, 0.32, 0.4, th, yaw + rng.uniform(-0.03, 0.03)))
                z += th


class StoneSlabTableFactory:
    """Display table of stacked rough-cut slabs (front +X): L x D x H = 1.8-2.6 x 1.0-1.2 x 0.75-0.8 m, split into 2-3 blocks 1 cm
    apart, ~12 layers per block, each layer jittered a little in plan and thickness; a lighter dressed top."""
    def __init__(self, seed):
        r = random.Random(seed)
        self.L = r.choice((1.8, 2.2, 2.6)); self.D = r.choice((1.0, 1.2)); self.H = r.choice((0.75, 0.8))
        self.blocks = r.choice((2, 3)); self.seed = seed

    def spawn_asset(self, i):
        r = random.Random(self.seed * 7 + i)
        side = _flat("ir_slab_stone", (0.15, 0.16, 0.18), 0.8, kind="stone")
        top = _flat("ir_slab_top", (0.3, 0.31, 0.32), 0.55, kind="stone")
        n = max(8, int(self.H / 0.064)); t = (self.H - 0.04) / n
        bl = (self.L - 0.01 * (self.blocks - 1)) / self.blocks
        sides, tops = [], []
        for b in range(self.blocks):
            cy = -self.L / 2 + bl / 2 + b * (bl + 0.01)
            for k in range(n):
                tk = t * r.uniform(0.88, 1.08)
                sides.append(("jbox", r.uniform(-0.02, 0.02), cy + r.uniform(-0.015, 0.015), 0.02 + k * t + tk / 2,
                              self.D - r.uniform(0, 0.05), bl - r.uniform(0, 0.04), tk, 0.012, 0.18, r.randrange(1 << 30)))
            tops.append(("jbox", 0, cy, self.H - 0.02, self.D + 0.02, bl + 0.01, 0.04, 0.006, 0.35, r.randrange(1 << 30)))
        groups = [(side, sides), (top, tops)]
        if STOCK:
            mats = _stock_mats(); st = {}
            _folded_stacks(r, 0.0, 0.0, self.D, self.L, self.H, mats, st)
            groups += [(mats[c], parts) for c, parts in st.items()]
        return mesh_object(f"StoneSlabTableFactory({self.seed}).spawn_asset({i})", groups)


#: hero rails (orchester, flagship r8): 4-6 cloth-simulated Infinigen shirts on the first CLOTH_RAILS rails of a scene; ROOM_FLAGSHIP_CLOTH=0 disables
CLOTH_RAILS = int(os.environ.get("ROOM_FLAGSHIP_CLOTH_RAILS", "4")) if os.environ.get("ROOM_FLAGSHIP_CLOTH", "1") != "0" else 0
_HERO = [0]


class WallRailFlatFactory:
    """Wall garment rail (front +X, back at x = 0, origin at the bottom of the bar; mount ~1.65 m): a 40 mm flat bar 0.16 m off the wall
    on brackets every ~1.2 m, blackened steel."""
    def __init__(self, seed):
        self.L = random.Random(seed).choice((2.4, 3.0, 3.6)); self.seed = seed

    def _hero_cloth(self, L, off, i):
        """The rail bar + hangers as one object, joined with 4-6 baked cloth shirts (no CLOTH modifier is left); None on any failure."""
        try:
            pa = _pa(); r = random.Random(self.seed * 29 + i)
            n = r.randint(4, 6); yaw0 = r.uniform(0.35, 0.6) * r.choice((1, -1)); shirts = []
            for k in range(n):
                sh = pa._cloth("shirt", "ShirtFactory", r.randrange(10 ** 6))
                if sh is None:
                    for x in shirts:
                        bpy.data.objects.remove(x, do_unlink=True)
                    return None
                top = max(v.co.y for v in sh.data.vertices)
                y = -L / 2 + 0.25 + (k + 0.5) * (L - 0.5) / n
                sh.rotation_euler = (math.pi / 2, 0, yaw0 + r.uniform(-0.05, 0.05)); sh.location = (off, y, -0.07 - top)
                shirts.append(sh)
            wall = bpy.data.objects.new("ir_drape_wall", bpy.data.meshes.new("ir_drape_wall"))    # a thin vertical collider at the wall (x = 0)
            bm = bmesh.new(); bmesh.ops.create_grid(bm, x_segments=1, y_segments=1, size=3.0); bm.to_mesh(wall.data); bm.free()
            wall.rotation_euler = (0, math.pi / 2, 0); wall.location = (0.0, 0.0, -0.8)
            pa._drape(shirts, pin_fn=lambda z, zmax: z > zmax - 0.09, colliders=[wall], frames=30)
            steel = _flat("ir_rail_steel", (0.11, 0.1, 0.09), 0.5, 0.9); black = _flat("ir_gar_fabric_black", PALETTE["black"], 0.85)
            prims = [("box", off, 0, 0.02, 0.008, L, 0.04)]
            nb = max(2, round(L / 1.2) + 1)
            for k in range(nb):
                yb = -L / 2 + 0.05 + k * (L - 0.1) / (nb - 1)
                prims += [("box", 0.004, yb, 0.02, 0.008, 0.05, 0.1), ("box", off / 2, yb, 0.012, off, 0.018, 0.024)]
            hang = [("box", off, sh.location.y, -0.035, 0.012, 0.4, 0.012, sh.rotation_euler[2]) for sh in shirts]
            base = mesh_object(f"WallRailFlatFactory({self.seed}).spawn_asset({i})", [(steel, prims), (black, hang)])
            return pa._join_cloth(base, shirts)
        except Exception as ex:                                   # noqa: BLE001 -- the box garments are the fallback, a scene never fails on cloth
            print(f"[flagship] hero cloth rail failed: {ex!r}"[:200])
            return None

    def spawn_asset(self, i):
        steel = _flat("ir_rail_steel", (0.11, 0.1, 0.09), 0.5, 0.9)
        L, off = self.L, 0.16
        nb = max(2, round(L / 1.2) + 1)
        prims = [("box", off, 0, 0.02, 0.008, L, 0.04)]
        for k in range(nb):
            y = -L / 2 + 0.05 + k * (L - 0.1) / (nb - 1)
            prims += [("box", 0.004, y, 0.02, 0.008, 0.05, 0.1), ("box", off / 2, y, 0.012, off, 0.018, 0.024)]
        groups = [(steel, prims)]
        if STOCK and CLOTH_RAILS and _HERO[0] < CLOTH_RAILS:             # the first rails of a scene are hero rails: Infinigen shirts, cloth-simulated
            _HERO[0] += 1
            hero = self._hero_cloth(L, off, i)
            if hero is not None:
                return hero
        if STOCK:
            r = random.Random(self.seed * 23 + i); mats = _stock_mats(); gar, hang = {}, []
            n = int((L - 0.2) / 0.29)
            for k in range(n):
                _hung_garment(r, -L / 2 + 0.15 + (k + 0.5) * (L - 0.3) / n, mats, gar, hang)
            groups += [(mats[c], parts) for c, parts in gar.items()] + [(mats["black"], hang)]
        return mesh_object(f"WallRailFlatFactory({self.seed}).spawn_asset({i})", groups)


class SteelLatticeScreenFactory:
    """Free-standing rusted steel grid screen (front +X, thin in x): 1.6-2.2 m wide x 2.6 m tall, 0.2 m pitch, a dark shaggy fabric swatch
    hung in most cells, two floor feet."""
    def __init__(self, seed):
        self.W = random.Random(seed).choice((1.6, 1.9, 2.2)); self.H = 2.6; self.seed = seed

    def spawn_asset(self, i):
        r = random.Random(self.seed * 11 + i)
        rust = _flat("ir_lattice_rust", (0.27, 0.13, 0.07), 0.65, 0.8)
        fabs = [_flat(f"ir_lattice_fabric_{k}", c, 0.95) for k, c in enumerate(((0.07, 0.06, 0.055), (0.12, 0.095, 0.075), (0.045, 0.045, 0.05)))]
        W, H, bar = self.W, self.H, 0.03
        nx, nz = max(4, round(W / 0.2)), round(H / 0.2)
        px, pz = W / nx, H / nz
        bars = [("box", 0, 0, 0.03 + H / 2, bar, bar, H + 0.04)] * 0 + \
               [("box", 0, -W / 2 + k * px, 0.05 + H / 2, bar, bar, H) for k in range(nx + 1)] + \
               [("box", 0.012, 0, 0.05 + k * pz, bar, W + bar, bar) for k in range(nz + 1)]
        bars += [("box", 0, s * (W / 2 - 0.05), 0.02, 0.05, 0.05, 0.04) for s in (1, -1)]
        feet = [("box", 0, s * (W / 2 - 0.05), 0.02, 0.45, 0.04, 0.04) for s in (1, -1)]
        swatches = [[], [], []]                                    # three dark browns / blacks; each swatch is 3 slightly rotated layers (ragged, fibrous edge)
        for a in range(nx):
            for b in range(nz):
                g = r.randrange(3)
                for layer in range(3):
                    swatches[g].append(("box", 0.02 + 0.004 * layer, -W / 2 + (a + 0.5) * px + r.uniform(-0.006, 0.006),
                                        0.05 + (b + 0.5) * pz + r.uniform(-0.006, 0.006), 0.012, px * r.uniform(0.66, 0.86),
                                        pz * r.uniform(0.66, 0.9), r.uniform(-0.18, 0.18)))
        return mesh_object(f"SteelLatticeScreenFactory({self.seed}).spawn_asset({i})", [(rust, bars + feet)] + [(f, sw) for f, sw in zip(fabs, swatches)], bevel=False)


class SteppedPlinthFactory:
    """Pale stone stepped plinth (front +X, origin at the bottom centre): three stacked rough-cut slabs 1.8 x 1.2 / 1.4 x 0.9 / 1.0 x 0.6 m,
    0.16 / 0.30 / 0.44 m high, each set back toward the rear (reference img 07: grey stone steps carrying folded goods)."""
    def __init__(self, seed):
        self.seed = seed

    def spawn_asset(self, i):
        r = random.Random(self.seed * 5 + i)
        stone = _flat("ir_plinth_stone", (0.6, 0.61, 0.6), 0.6, kind="stone")
        parts = []
        for k, (d, w, h) in enumerate(((1.2, 1.8, 0.16), (0.9, 1.4, 0.30), (0.6, 1.0, 0.44))):
            parts.append(("jbox", -0.05 * k + r.uniform(-0.01, 0.01), r.uniform(-0.01, 0.01), h / 2, d, w, h, 0.008, 0.2, r.randrange(1 << 30)))
        return mesh_object(f"SteppedPlinthFactory({self.seed}).spawn_asset({i})", [(stone, parts)])


def _lobby_wood_wall():
    from room_planner.proc_clinic_lobby import WoodPanelWallFactory
    return WoodPanelWallFactory


class FlagshipWoodWallFactory:
    """The warm oak panel wall of the flagship (VLM: 'warm oak-panel wall missing'): proc_clinic_lobby.WoodPanelWallFactory, 3.6 m wide, back at x = 0."""
    def __new__(cls, seed):
        return _lobby_wood_wall()(seed)
