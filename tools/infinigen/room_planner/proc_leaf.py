"""Realistic leaves for the procedural plants (atrium planting, PottedPlantFactory): card-thin curved leaf surfaces with a leaf texture (midrib, veins, edge-to-centre gradient), per-leaf colour jitter in a
vertex colour layer, subtle subsurface, pinnate palm fronds (many narrow leaflets along an arching rachis), broad fig / monstera leaves, small ficus leaves and fern fronds.

    lv = Leaves(); lv.leaf(...); lv.frond(...); obj = lv.object(name)

A leaf is a (nu x nv) grid: the centre line arches (gravity), the width follows a shape profile (ovate / blade), the blade is cupped across (curl). UV u = across (0..1), v = base to tip (0..1).
Textures: data/venue_refs/leaf_tex/leaf_ovate.png / leaf_blade.png (leaf_tex.py, system python)."""
from __future__ import annotations

import math
import random
import subprocess
from pathlib import Path

import bmesh
import bpy
from mathutils import Vector

TEX = Path("/jarvis/project/robomituba/data/venue_refs/leaf_tex")


def _tex(name):
    f = TEX / f"leaf_{name}.png"
    if not f.exists():
        try:
            subprocess.run(["python3", str(Path(__file__).with_name("leaf_tex.py"))], check=True, timeout=120)
        except Exception as ex:                                  # noqa: BLE001 -- flat green without it
            print(f"leaf texture not built: {ex!r}"[:150], flush=True)
    return f if f.exists() else None


def leaf_mat(name, tint, tex="ovate", rough=0.42, sss=0.14):
    m = bpy.data.materials.get(name)
    if m is not None:
        return m
    m = bpy.data.materials.new(name); m.use_nodes = True; nt = m.node_tree; b = nt.nodes["Principled BSDF"]
    b.inputs["Roughness"].default_value = rough
    for k in ("Specular IOR Level", "Specular"):
        if k in b.inputs:
            b.inputs[k].default_value = 0.35
    if "Subsurface Weight" in b.inputs:
        b.inputs["Subsurface Weight"].default_value = sss; b.inputs["Subsurface Radius"].default_value = (0.35, 0.9, 0.15); b.inputs["Subsurface Scale"].default_value = 0.01
    col = nt.nodes.new("ShaderNodeAttribute"); col.attribute_name = "leaf_tint"; col.attribute_type = "GEOMETRY"
    mix = nt.nodes.new("ShaderNodeMix"); mix.data_type = "RGBA"; mix.blend_type = "MULTIPLY"; mix.inputs[0].default_value = 1.0
    f = _tex(tex)
    if f is not None:
        tx = nt.nodes.new("ShaderNodeTexImage"); tx.image = bpy.data.images.load(str(f), check_existing=True); tx.image.colorspace_settings.name = "sRGB"
        mul = nt.nodes.new("ShaderNodeMix"); mul.data_type = "RGBA"; mul.blend_type = "MULTIPLY"; mul.inputs[0].default_value = 1.0; mul.inputs[7].default_value = (*tint, 1)
        nt.links.new(tx.outputs["Color"], mul.inputs[6]); nt.links.new(mul.outputs[2], mix.inputs[6])
    else:
        mix.inputs[6].default_value = (*tint, 1)
    nt.links.new(col.outputs["Color"], mix.inputs[7]); nt.links.new(mix.outputs[2], b.inputs["Base Color"])
    return m


class Leaves:
    def __init__(self, seed=1):
        self.bm = bmesh.new(); self.uv = self.bm.loops.layers.uv.verify(); self.cl = self.bm.loops.layers.float_color.new("leaf_tint") if hasattr(self.bm.loops.layers, "float_color") else self.bm.loops.layers.color.new("leaf_tint")
        self.slots = {}; self.mats = []; self.r = random.Random(seed)

    def _slot(self, mat):
        if mat.name not in self.slots:
            self.slots[mat.name] = len(self.mats); self.mats.append(mat)
        return self.slots[mat.name]

    @staticmethod
    def _wf(shape, t):
        if shape == "blade":
            return max(0.0, math.sin(math.pi * min(1.0, t * 0.97 + 0.015))) ** 0.9
        return max(0.0, math.sin(math.pi * min(1.0, t ** 0.75))) ** 0.75 * (1.0 - 0.25 * t)

    def leaf(self, mat, base, dirv, length, width, shape="ovate", curl=0.25, arch=0.3, nu=3, nv=5, tint=0.18, up=None):
        """One leaf from `base` along `dirv` (unit), `length` x `width` metres; arch = how far the tip drops (fraction of the length), curl = cupping across the width (fraction of the width)."""
        r = self.r; i = self._slot(mat); d = Vector(dirv).normalized(); up = Vector(up) if up is not None else Vector((0, 0, 1))
        side = d.cross(up)
        if side.length < 1e-3:
            side = Vector((1, 0, 0))
        side.normalize(); nrm = side.cross(d).normalized()
        j = (1.0 + r.uniform(-tint, tint), 1.0 + r.uniform(-tint, tint) * 0.6, 1.0 + r.uniform(-tint, tint) * 1.4)                  # per-leaf colour jitter (a little yellower / bluer, lighter / darker)
        rows = []
        for q in range(nv + 1):
            t = q / nv; w = self._wf(shape, t) * width / 2; c = Vector(base) + d * (length * t) + Vector((0, 0, -1)) * (arch * length * t * t)
            row = []
            for p in range(nu + 1):
                s = p / nu * 2 - 1; pos = c + side * (s * w) + nrm * (curl * w * s * s)
                v = self.bm.verts.new(pos); row.append((v, s, t))
            rows.append(row)
        for a, b in zip(rows, rows[1:]):
            for p in range(nu):
                vs = [a[p], a[p + 1], b[p + 1], b[p]]
                if len({id(x[0]) for x in vs}) < 4 or (vs[0][0].co - vs[1][0].co).length + (vs[2][0].co - vs[3][0].co).length < 1e-6 and (vs[0][0].co - vs[3][0].co).length < 1e-6:
                    continue
                try:
                    f = self.bm.faces.new([x[0] for x in vs])
                except ValueError:
                    continue
                f.material_index = i; f.smooth = True
                for lp, (v, s, t) in zip(f.loops, vs):
                    lp[self.uv].uv = ((s + 1) / 2, t); lp[self.cl] = (min(1.4, j[0]), min(1.4, j[1]), min(1.4, j[2]), 1.0)

    def frond(self, mat, base, azimuth, length, up0, leaflet_len, leaflet_w, pairs=14, droop=0.9, lift=0.5):
        """A pinnate palm / fern frond: an arching rachis (a thin leaf strip) with `pairs` pairs of narrow leaflets, shortest at the base and the tip, swept forward and drooping."""
        c = Vector(base); ca, sa = math.cos(azimuth), math.sin(azimuth); prev = c; pts = []
        for q in range(0, 9):
            t = q / 8.0
            pts.append(c + Vector((ca * length * t * 0.9, sa * length * t * 0.9, length * (up0 * t - droop * t * t) * 0.9)))
        for a, b in zip(pts, pts[1:]):
            self.leaf(mat, a, b - a, (b - a).length * 1.02, 0.012, "blade", 0.1, 0.0, 1, 1, 0.1)
        for q in range(pairs):
            t = (q + 0.5) / pairs; f = t * 8; k = min(7, int(f)); p = pts[k].lerp(pts[k + 1], f - k); tang = (pts[k + 1] - pts[k]).normalized()
            ll = leaflet_len * math.sin(math.pi * (0.12 + 0.8 * t)) ** 0.6
            for sg in (1, -1):
                out = Vector((-sa * sg, ca * sg, 0.0)); dirv = (out * 0.9 + tang * (0.55 + 0.25 * lift) + Vector((0, 0, -0.35 - 0.3 * t))).normalized()
                self.leaf(mat, p, dirv, ll, leaflet_w, "blade", 0.15, 0.25 + 0.2 * t, 2, 3, 0.15)

    def object(self, name):
        me = bpy.data.meshes.new(name); self.bm.to_mesh(me); self.bm.free()
        for m in self.mats:
            me.materials.append(m)
        for p in me.polygons:
            p.use_smooth = True
        o = bpy.data.objects.new(name, me); bpy.context.scene.collection.objects.link(o)
        return o


def mats():
    return {"fig": leaf_mat("ir_lf_fig", (0.5, 0.78, 0.42), "ovate", 0.32), "palm": leaf_mat("ir_lf_palm", (0.8, 1.0, 0.7), "blade", 0.45), "mon": leaf_mat("ir_lf_monstera", (0.5, 0.82, 0.5), "ovate", 0.33),
            "ficus": leaf_mat("ir_lf_ficus", (0.7, 0.95, 0.55), "ovate", 0.4), "fern": leaf_mat("ir_lf_fern", (0.85, 1.0, 0.7), "blade", 0.5)}


# ----- plant assemblies. Each returns nothing; leaves go into `lv`, stems (cylinders) into `stems` as ("cyl", centre, (r_bottom, r_top, h), rot) for pa._prims. ------------------------------------------------
def _stem(stems, p0, p1, rb, rt):
    v = (p1[0] - p0[0], p1[1] - p0[1], p1[2] - p0[2]); ln = math.sqrt(sum(q * q for q in v)) or 1e-3
    stems.append(("cyl", tuple((p0[k] + p1[k]) / 2 for k in range(3)), (rb, rt, ln), (0.0, math.acos(max(-1.0, min(1.0, v[2] / ln))), math.atan2(v[1], v[0]))))


def fig(lv, stems, mt, r, ox, oy, zb, h, sc=1.0):
    lean = (r.uniform(-0.06, 0.06) * sc, r.uniform(-0.06, 0.06) * sc); trunk = [(ox + lean[0] * k / 6, oy + lean[1] * k / 6, zb + h * 0.72 * k / 6) for k in range(7)]
    for k in range(6):
        _stem(stems, trunk[k], trunk[k + 1], (0.05 - 0.004 * k) * sc, (0.05 - 0.004 * (k + 1)) * sc)
    tip = trunk[-1]
    for b in range(8):
        az = b * 2 * math.pi / 8 + r.uniform(-0.3, 0.3); base = (ox + lean[0] * 0.8, oy + lean[1] * 0.8, zb + min(h * (0.5 + 0.5 * b / 7), h * 0.72)); reach = r.uniform(0.4, 0.75) * sc
        end = (base[0] + math.cos(az) * reach, base[1] + math.sin(az) * reach, base[2] + r.uniform(0.12, 0.4) * sc); _stem(stems, base, end, 0.014 * sc, 0.008 * sc)
        for q in range(int(14 * (0.5 + 0.5 * sc))):
            a2 = az + r.uniform(-1.5, 1.5); t = r.uniform(0.0, 0.3) * sc; c = (end[0] + math.cos(a2) * t, end[1] + math.sin(a2) * t, end[2] + r.uniform(-0.15, 0.2) * sc)
            el = r.uniform(-0.1, 0.9); d = (math.cos(a2) * math.cos(el), math.sin(a2) * math.cos(el), math.sin(el))
            lv.leaf(mt["fig"], c, d, r.uniform(0.14, 0.24) * sc, r.uniform(0.09, 0.15) * sc, "ovate", 0.3, 0.3)
    for q in range(int(24 * (0.5 + 0.5 * sc))):
        a2 = r.uniform(0, 2 * math.pi); t = r.uniform(0.0, 0.25) * sc; el = r.uniform(0.2, 1.2)
        lv.leaf(mt["fig"], (tip[0] + math.cos(a2) * t, tip[1] + math.sin(a2) * t, tip[2] + r.uniform(0, 0.3) * sc), (math.cos(a2) * math.cos(el), math.sin(a2) * math.cos(el), math.sin(el)), r.uniform(0.15, 0.25) * sc, r.uniform(0.1, 0.16) * sc, "ovate", 0.3, 0.2)


def palm(lv, stems, mt, r, ox, oy, zb, n_stems, hmin, hmax, sc=1.0):
    for s_ in range(n_stems):
        a0 = r.uniform(0, 2 * math.pi); off = r.uniform(0.04, 0.18) * sc; h = r.uniform(hmin, hmax); x0, y0 = ox + math.cos(a0) * off, oy + math.sin(a0) * off
        tp = (x0 + math.cos(a0) * 0.1 * sc, y0 + math.sin(a0) * 0.1 * sc, zb + h); _stem(stems, (x0, y0, zb), tp, 0.014 * sc, 0.009 * sc)
        for f in range(r.randint(9, 12)):
            az = f * 2 * math.pi / 10.5 + r.uniform(-0.25, 0.25)
            lv.frond(mt["palm"], tp, az, r.uniform(0.9, 1.3) * sc, r.uniform(0.3, 0.8), r.uniform(0.2, 0.3) * sc, 0.022 * sc, pairs=int(12 + 6 * sc))


def monstera(lv, stems, mt, r, ox, oy, zb, n, sc=1.0):
    for q in range(n):
        az = r.uniform(0, 2 * math.pi); ln = r.uniform(0.3, 0.8) * sc; h = r.uniform(0.3, 0.85) * sc; tp = (ox + math.cos(az) * ln * 0.55, oy + math.sin(az) * ln * 0.55, zb + h)
        _stem(stems, (ox, oy, zb), tp, 0.009 * sc, 0.006 * sc)
        lv.leaf(mt["mon"], (tp[0], tp[1], tp[2] + 0.02), (math.cos(az) * 0.8, math.sin(az) * 0.8, -0.25), r.uniform(0.2, 0.3) * sc, r.uniform(0.17, 0.26) * sc, "ovate", 0.4, 0.15, 4, 6)


def ficus(lv, stems, mt, r, ox, oy, zb, h, sc=1.0):
    _stem(stems, (ox, oy, zb), (ox, oy, zb + h), 0.016 * sc, 0.009 * sc)
    for b in range(8):
        az = b * 2 * math.pi / 8 + r.uniform(-0.3, 0.3); base = (ox, oy, zb + h * r.uniform(0.45, 0.92)); end = (ox + math.cos(az) * 0.3 * sc, oy + math.sin(az) * 0.3 * sc, base[2] + r.uniform(0.1, 0.3) * sc); _stem(stems, base, end, 0.006 * sc, 0.003 * sc)
        for q in range(int(34 * (0.5 + 0.5 * sc))):
            a2 = az + r.uniform(-1.4, 1.4); t = r.uniform(0, 0.2) * sc; el = r.uniform(-0.3, 0.9)
            lv.leaf(mt["ficus"], (end[0] + math.cos(a2) * t, end[1] + math.sin(a2) * t, end[2] + r.uniform(-0.1, 0.15) * sc), (math.cos(a2) * math.cos(el), math.sin(a2) * math.cos(el), math.sin(el)),
                    r.uniform(0.05, 0.08) * sc, r.uniform(0.028, 0.045) * sc, "ovate", 0.2, 0.2, 2, 4)


def ferns(lv, mt, r, cx, cy, zb, n, spread_x, spread_y, sc=1.0):
    for q in range(n):
        x, y = cx + r.uniform(-spread_x, spread_x), cy + r.uniform(-spread_y, spread_y)
        for f in range(r.randint(5, 7)):
            lv.frond(mt["fern"], (x, y, zb + 0.03), f * 2 * math.pi / 6 + r.uniform(-0.3, 0.3), r.uniform(0.3, 0.5) * sc, r.uniform(0.3, 0.7), 0.1 * sc, 0.014 * sc, pairs=8, droop=0.8)
