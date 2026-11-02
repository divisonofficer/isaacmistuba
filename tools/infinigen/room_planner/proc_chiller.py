"""Open-front multideck chiller with realistic stock (user 10-23: 'products with use and material feel'; follow-up: geometry, silhouette variety, packaging graphics, LED lighting, controlled disorder first, dirt last).

    OpenChillerFactory(seed).spawn_asset(i)     LEN = layout size_m[0] (class attr, default 1.8 m), 0.78 m deep, 2.0 m tall, back at x = 0, front +X

Structure: powder-coated sheet-metal body with every edge beveled (BEVEL 1.5 mm + weighted normal on the object), canopy with a backlit sign panel (abstract glyph blocks, no text), a perforated cold-air back liner
with slot rows, glass end panels, a louvred intake grille, a cable duct with bolts, five brushed-steel shelves that slope to the front with a folded lip, a plastic price rail carrying price tags, clear plastic shelf
stoppers, cool LED strips at every shelf front, and one rect area light per strip so the goods are lit from above like a real unit.
Stock: ~30 product silhouettes built as lathes / boxes / crinkled film bags with randomised proportions (PET bottles 350 ml - 1.5 L with different necks, waists and caps, cans, glass bottles, gable milk cartons,
brick packs with straws, HDPE milk jugs with handles, yogurt cups / tubs / drinks, glass jars, deli tubs with domed lids, wedge sandwiches, kimbap packs, sushi trays, onigiri, bread and salad bags, cheese / butter
blocks, clamshell cakes, dessert cups). Labels are wrap-around prints from the 100-design atlas (pack_atlas.py): logo shapes, glyph wordmarks, tiny pseudo-text, nutrition tables, barcodes, seams. Shelves are arranged
as facings with controlled disorder: per-item +-5-15 mm position, +-2-5 deg yaw, depth differences, gaps, half-empty shelves, pairs, a misplaced product, a knocked-over one, hidden items at the back."""
from __future__ import annotations

import math
import os
import random
import subprocess
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Euler, Matrix, Vector

from room_planner import proc_assets as pa

ATLAS = Path("/jarvis/project/robomituba/data/venue_refs/pack_atlas/pack_atlas.png")
NC = 10                                                       # atlas cells per side


def _atlas():
    if not ATLAS.exists():
        try:
            subprocess.run(["python3", str(Path(__file__).with_name("pack_atlas.py"))], check=True, timeout=120)
        except Exception as ex:                               # noqa: BLE001 -- flat colours without it
            print(f"pack atlas not built: {ex!r}"[:150], flush=True)
    return ATLAS if ATLAS.exists() else None


class M:
    """Accumulates primitives into ONE bmesh, one material slot per material."""

    def __init__(self):
        self.bm = bmesh.new(); self.uv = self.bm.loops.layers.uv.verify(); self.slots = {}; self.mats = []

    def sl(self, mat):
        if mat.name not in self.slots:
            self.slots[mat.name] = len(self.mats); self.mats.append(mat)
        return self.slots[mat.name]

    def _put(self, verts, rot, c):
        bmesh.ops.transform(self.bm, matrix=Matrix.Translation(c) @ Euler(rot).to_matrix().to_4x4(), verts=verts)

    def _uv(self, f, cell, uvs):
        if cell is None:
            for lp in f.loops:
                lp[self.uv].uv = (0.0, 0.0)
            return
        k = cell % (NC * NC); cu, cv = (k % NC) / NC, 1.0 - (k // NC + 1) / NC
        for lp, (a, b) in zip(f.loops, uvs):
            lp[self.uv].uv = (cu + (0.004 + 0.992 * min(max(a, 0.0), 1.0)) / NC, cv + (0.004 + 0.992 * min(max(b, 0.0), 1.0)) / NC)

    def box(self, mat, c, size, rot=(0, 0, 0), cell=None, smooth=False):
        i = self.sl(mat); sx, sy, sz = size[0] / 2, size[1] / 2, size[2] / 2
        v = [self.bm.verts.new((x * sx, y * sy, z * sz)) for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)]       # index = 4*(x>0) + 2*(y>0) + (z>0)
        idx = lambda x, y, z: 4 * x + 2 * y + z
        quads = {"+x": ((1, 0, 0), (1, 1, 0), (1, 1, 1), (1, 0, 1)), "-x": ((0, 1, 0), (0, 0, 0), (0, 0, 1), (0, 1, 1)), "+y": ((1, 1, 0), (0, 1, 0), (0, 1, 1), (1, 1, 1)),
                 "-y": ((0, 0, 0), (1, 0, 0), (1, 0, 1), (0, 0, 1)), "+z": ((0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)), "-z": ((0, 1, 0), (1, 1, 0), (1, 0, 0), (0, 0, 0))}
        for q in quads.values():
            f = self.bm.faces.new([v[idx(*p)] for p in q]); f.material_index = i; f.smooth = smooth
            self._uv(f, cell, [(0, 0), (1, 0), (1, 1), (0, 1)])
        self._put(v, rot, c)

    def lathe(self, body, c, profile, rot=(0, 0, 0), seg=18, label=None, cell=None, smooth=True, cap=True):
        """Surface of revolution about z: profile = [(r, z)] bottom to top. label = (mat, z0, z1): quads inside that z band get the label material with wrap-around atlas UVs."""
        ib = self.sl(body); rings = []; allv = []
        for r, z in profile:
            ring = [self.bm.verts.new((r * math.cos(2 * math.pi * k / seg), r * math.sin(2 * math.pi * k / seg), z)) for k in range(seg)]; rings.append(ring); allv += ring
        for a, b, (p0, p1) in zip(rings, rings[1:], zip(profile, profile[1:])):
            zm = (p0[1] + p1[1]) / 2; lab = label is not None and label[1] <= zm <= label[2]
            for k in range(seg):
                f = self.bm.faces.new((a[k], a[(k + 1) % seg], b[(k + 1) % seg], b[k])); f.smooth = smooth
                if lab:
                    f.material_index = self.sl(label[0]); z0, z1 = label[1], label[2]
                    self._uv(f, cell if cell is not None else 0, [(k / seg, (p0[1] - z0) / (z1 - z0)), ((k + 1) / seg, (p0[1] - z0) / (z1 - z0)), ((k + 1) / seg, (p1[1] - z0) / (z1 - z0)), (k / seg, (p1[1] - z0) / (z1 - z0))])
                else:
                    f.material_index = ib; self._uv(f, None, [(0, 0)] * 4)
        if cap:
            for ring, up in ((rings[0], False), (rings[-1], True)):
                if profile[0 if not up else -1][0] > 1e-4:
                    f = self.bm.faces.new(ring if up else list(reversed(ring))); f.material_index = ib; f.smooth = False; self._uv(f, None, [(0, 0)] * seg)
        self._put(allv, rot, c)

    def ellip(self, mat, c, size, rot=(0, 0, 0), jitter=0.0, rng=None, smooth=True):
        i = self.sl(mat); r = bmesh.ops.create_icosphere(self.bm, subdivisions=2, radius=1.0, calc_uvs=False)
        vs = r["verts"]
        for v in vs:
            v.co.x *= size[0]; v.co.y *= size[1]; v.co.z *= size[2]
            if jitter and rng is not None:
                v.co += Vector((rng.uniform(-jitter, jitter), rng.uniform(-jitter, jitter), rng.uniform(-jitter, jitter)))
        for f in {f for v in vs for f in v.link_faces}:
            f.material_index = i; f.smooth = smooth
            for lp in f.loops:
                lp[self.uv].uv = (0.0, 0.0)
        self._put(vs, rot, c)

    def object(self, name):
        me = bpy.data.meshes.new(name); self.bm.to_mesh(me); self.bm.free()
        for m in self.mats:
            me.materials.append(m)
        o = bpy.data.objects.new(name, me); bpy.context.scene.collection.objects.link(o)
        return o


# ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
def _mat(name, rgb, rough, metallic=0.0, trans=0.0, ior=None, emit=None, aniso=0.0, bump=None):
    m = bpy.data.materials.get(name)
    if m is not None:
        return m
    m = bpy.data.materials.new(name); m.use_nodes = True; nt = m.node_tree; b = nt.nodes["Principled BSDF"]
    b.inputs["Base Color"].default_value = (*rgb, 1); b.inputs["Roughness"].default_value = rough; b.inputs["Metallic"].default_value = metallic
    if trans:
        b.inputs["Transmission Weight"].default_value = trans
    if ior:
        b.inputs["IOR"].default_value = ior
    if emit:
        b.inputs["Emission Color"].default_value = (*emit[0], 1); b.inputs["Emission Strength"].default_value = emit[1]
    if aniso:
        b.inputs["Anisotropic"].default_value = aniso
    if bump:                                                  # (scale, strength): a high-frequency noise normal (orange peel / film crinkle)
        tc = nt.nodes.new("ShaderNodeTexCoord"); nz = nt.nodes.new("ShaderNodeTexNoise"); nz.inputs["Scale"].default_value = bump[0]; nz.inputs["Detail"].default_value = 8.0; nz.inputs["Roughness"].default_value = 0.7
        bp = nt.nodes.new("ShaderNodeBump"); bp.inputs["Strength"].default_value = bump[1]
        nt.links.new(tc.outputs["Object"], nz.inputs["Vector"]); nt.links.new(nz.outputs["Fac"], bp.inputs["Height"]); nt.links.new(bp.outputs["Normal"], b.inputs["Normal"])
    return m


def _pack(name, rough, spec=0.5):
    m = bpy.data.materials.get(name)
    if m is not None:
        return m
    m = bpy.data.materials.new(name); m.use_nodes = True; nt = m.node_tree; b = nt.nodes["Principled BSDF"]; b.inputs["Roughness"].default_value = rough
    for k in ("Specular IOR Level", "Specular"):
        if k in b.inputs:
            b.inputs[k].default_value = spec
    at = _atlas()
    if at is not None:
        tx = nt.nodes.new("ShaderNodeTexImage"); tx.image = bpy.data.images.load(str(at), check_existing=True); tx.image.colorspace_settings.name = "sRGB"; tx.interpolation = "Linear"
        nt.links.new(tx.outputs["Color"], b.inputs["Base Color"])
    else:
        b.inputs["Base Color"].default_value = (0.8, 0.8, 0.8, 1)
    return m


class Mats:
    def __init__(self):
        mk = _mat
        self.pc = mk("ir_oc2_powder", (0.035, 0.035, 0.04), 0.42, 0.0, bump=(60.0, 0.12)); self.pcw = mk("ir_oc2_white_body", (0.88, 0.89, 0.9), 0.4, bump=(60.0, 0.1))
        self.steel = mk("ir_oc2_brushed", (0.72, 0.74, 0.76), 0.3, 1.0, aniso=0.7); self.rail = mk("ir_oc2_rail", (0.92, 0.93, 0.93), 0.2)
        self.clear = mk("ir_oc2_clear", (0.9, 0.95, 0.95), 0.05, 0.0, trans=0.92, ior=1.45); self.sglass = mk("ir_oc2_sideglass", (0.8, 0.88, 0.9), 0.03, 0.0, trans=0.85, ior=1.5)
        self.led = mk("ir_oc2_led", (0.9, 0.96, 1.0), 0.4, emit=((0.85, 0.94, 1.0), 10.0)); self.liner = mk("ir_oc2_liner", (0.82, 0.9, 0.97), 0.4, emit=((0.75, 0.88, 1.0), 0.6)); self.sign = mk("ir_oc2_sign", (0.95, 0.96, 0.96), 0.4, emit=((1.0, 1.0, 1.0), 2.2))
        self.ink = mk("ir_oc2_ink", (0.03, 0.03, 0.035), 0.5); self.tag = mk("ir_oc2_tag", (0.95, 0.95, 0.9), 0.55)
        self.pet = mk("ir_oc2_pet", (0.9, 0.95, 0.96), 0.06, 0.0, trans=0.9, ior=1.45); self.glassb = mk("ir_oc2_glassbottle", (0.1, 0.18, 0.08), 0.05, 0.0, trans=0.8, ior=1.5)
        self.liq = [mk(f"ir_oc2_liq{k}", c, 0.15) for k, c in enumerate(((0.55, 0.28, 0.05), (0.7, 0.06, 0.04), (0.9, 0.62, 0.06), (0.65, 0.78, 0.2), (0.15, 0.08, 0.04), (0.9, 0.92, 0.9), (0.85, 0.35, 0.05)))]
        self.matte = _pack("ir_oc2_pack_matte", 0.62, 0.3); self.gloss = _pack("ir_oc2_pack_gloss", 0.22, 0.6)
        self.foil = mk("ir_oc2_foil", (0.8, 0.82, 0.85), 0.22, 1.0, bump=(80.0, 0.08)); self.can = mk("ir_oc2_can", (0.85, 0.86, 0.88), 0.28, 1.0)
        self.film = mk("ir_oc2_film", (0.95, 0.96, 0.96), 0.28, 0.0, trans=0.6, bump=(110.0, 0.4)); self.bag = mk("ir_oc2_bag", (0.93, 0.87, 0.7), 0.3, 0.0, trans=0.5, bump=(110.0, 0.4))
        self.bread = mk("ir_oc2_bread", (0.72, 0.5, 0.25), 0.6); self.green = mk("ir_oc2_green", (0.13, 0.38, 0.09), 0.6); self.cream = mk("ir_oc2_cream", (0.95, 0.9, 0.78), 0.6); self.choc = mk("ir_oc2_choc", (0.17, 0.08, 0.045), 0.6)
        self.rice = mk("ir_oc2_rice", (0.93, 0.93, 0.9), 0.7); self.nori = mk("ir_oc2_nori", (0.02, 0.03, 0.02), 0.5); self.cheese = mk("ir_oc2_cheese", (0.9, 0.7, 0.2), 0.5); self.butter = mk("ir_oc2_butter", (0.95, 0.88, 0.5), 0.5)
        self.cap = [mk(f"ir_oc2_cap{k}", c, 0.3) for k, c in enumerate(((0.8, 0.08, 0.06), (0.1, 0.3, 0.7), (0.95, 0.95, 0.9), (0.1, 0.5, 0.2), (0.9, 0.7, 0.1), (0.05, 0.05, 0.06)))]


# ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
class Stock:
    """Product builders: each places one item with its base at the local origin (x, y, z) already on the shelf plane and returns (depth along x, width along y)."""

    def __init__(self, m, k, rng):
        self.m, self.k, self.r = m, k, rng

    def _cap(self):
        return self.r.choice(self.k.cap)

    def bottle(self, x, y, z, yaw, tilt, cell, kind=None):
        m, r, k = self.m, self.r, self.k
        kind = kind or r.choice(("classic", "classic", "waist", "tall", "wide", "square", "juice"))
        h = {"classic": r.choice((0.19, 0.22, 0.25)), "waist": r.uniform(0.2, 0.24), "tall": r.uniform(0.26, 0.3), "wide": r.uniform(0.17, 0.2), "square": r.uniform(0.18, 0.22), "juice": r.uniform(0.2, 0.26)}[kind]
        rr = {"classic": r.uniform(0.026, 0.034), "waist": r.uniform(0.03, 0.035), "tall": r.uniform(0.024, 0.028), "wide": r.uniform(0.036, 0.043), "square": r.uniform(0.032, 0.038), "juice": r.uniform(0.03, 0.04)}[kind]
        nr = rr * r.uniform(0.38, 0.5); sh = r.uniform(0.04, 0.07); cap_r = nr * 1.15; cap_h = r.uniform(0.014, 0.024); lvl = r.uniform(0.7, 0.85)
        prof = [(0.0, 0.0), (rr * 0.85, 0.0), (rr, 0.008), (rr, h - sh - 0.01)] if kind != "waist" else [(0.0, 0.0), (rr * 0.85, 0.0), (rr, 0.008), (rr, h * 0.3), (rr * 0.88, h * 0.42), (rr * 0.88, h * 0.52), (rr, h * 0.64), (rr, h - sh - 0.01)]
        prof += [(rr * 0.8, h - sh * 0.55), (nr * 1.25, h - 0.018), (nr, h - 0.012), (nr, h)]
        lab0, lab1 = h * 0.22, h * r.uniform(0.62, 0.72)
        tl = Matrix.Rotation(yaw, 3, "Z")
        m.lathe(k.pet, (x, y, z), prof, (tilt[0], tilt[1], yaw), seg=16, label=(k.gloss, lab0, lab1), cell=cell)                       # clear PET with a wrap-around printed label
        liq = r.choice(k.liq); lh = h * lvl
        m.lathe(liq, (x, y, z + 0.004), [(0, 0), (rr * 0.93, 0), (rr * 0.93, min(lh, h - sh - 0.01)), (rr * 0.75, min(lh, h - sh + 0.01)), (0, min(lh, h - sh + 0.01))], (tilt[0], tilt[1], yaw), seg=14, cap=False)    # the liquid
        m.lathe(self._cap(), (x, y, z + h - 0.002), [(0, 0), (cap_r, 0), (cap_r, cap_h), (cap_r * 0.92, cap_h + 0.002), (0, cap_h + 0.002)], (tilt[0], tilt[1], yaw), seg=12)
        return rr * 2, rr * 2

    def can(self, x, y, z, yaw, tilt, cell):
        m, r, k = self.m, self.r, self.k
        slim = r.random() < 0.3; rr = 0.026 if slim else 0.033; h = 0.135 if slim else 0.122
        prof = [(0, 0), (rr * 0.82, 0), (rr * 0.82, 0.004), (rr, 0.012), (rr, h - 0.014), (rr * 0.84, h - 0.004), (rr * 0.8, h), (0, h)]
        m.lathe(k.can, (x, y, z), prof, (tilt[0], tilt[1], yaw), seg=16, label=(k.gloss, 0.016, h - 0.018), cell=cell)
        return rr * 2, rr * 2

    def glass_bottle(self, x, y, z, yaw, tilt, cell):
        m, r, k = self.m, self.r, self.k; rr = r.uniform(0.025, 0.032); h = r.uniform(0.2, 0.26); nr = rr * 0.38
        prof = [(0, 0), (rr * 0.9, 0), (rr, 0.01), (rr, h * 0.5), (rr * 0.6, h * 0.66), (nr, h * 0.75), (nr, h)]
        m.lathe(k.glassb, (x, y, z), prof, (tilt[0], tilt[1], yaw), seg=14, label=(k.matte, h * 0.2, h * 0.5), cell=cell)
        m.lathe(self._cap(), (x, y, z + h - 0.003), [(0, 0), (nr * 1.2, 0), (nr * 1.2, 0.014), (0, 0.014)], (tilt[0], tilt[1], yaw), seg=10)
        return rr * 2, rr * 2

    def carton(self, x, y, z, yaw, tilt, cell, gable=True):
        m, r, k = self.m, self.r, self.k
        w, d, h = (r.choice((0.07, 0.095)), r.choice((0.07, 0.095)), r.choice((0.19, 0.24))) if gable else (0.07, 0.045, r.choice((0.11, 0.14)))
        rot = (tilt[0], tilt[1], yaw)
        m.box(k.matte, (x, y, z + h / 2), (d, w, h), rot, cell=cell)
        if gable:
            for sg in (1, -1):
                m.box(k.matte, (x, y, z + h + 0.012), (d * 0.55, w, 0.008), (rot[0], rot[1] + sg * 0.55, yaw), cell=cell)
            m.box(k.matte, (x, y, z + h + 0.03), (0.006, w, 0.022), rot, cell=cell)
        else:                                                                                  # a brick pack with a straw
            m.box(k.cap[2], (x - d * 0.2, y, z + h + 0.002), (0.012, 0.012, 0.004), rot)
        return d, w

    def jug(self, x, y, z, yaw, tilt, cell):
        m, r, k = self.m, self.r, self.k; w, d, h = r.choice((0.1, 0.12)), 0.075, r.choice((0.2, 0.24)); rot = (tilt[0], tilt[1], yaw)
        m.box(k.pet, (x, y, z + h / 2), (d, w, h), rot); m.box(k.liq[5], (x, y, z + h * 0.42), (d * 0.94, w * 0.94, h * 0.78), rot)
        m.box(k.gloss, (x + d / 2 + 0.001, y, z + h * 0.45), (0.002, w * 0.8, h * 0.4), rot, cell=cell)
        m.lathe(self._cap(), (x, y, z + h), [(0, 0), (0.022, 0), (0.022, 0.025), (0, 0.025)], rot, seg=10)
        m.box(k.pet, (x - d * 0.3, y + w / 2 - 0.012, z + h * 0.7), (0.02, 0.016, h * 0.4), rot)                    # the handle
        return d, w

    def cup(self, x, y, z, yaw, tilt, cell, kind=None):
        m, r, k = self.m, self.r, self.k
        kind = kind or r.choice(("small", "tall", "tub", "drink"))
        rt, rb, h = {"small": (0.036, 0.028, 0.075), "tall": (0.03, 0.025, 0.1), "tub": (0.055, 0.042, 0.085), "drink": (0.026, 0.026, 0.1)}[kind]
        rot = (tilt[0], tilt[1], yaw)
        m.lathe(k.matte, (x, y, z), [(0, 0), (rb, 0), (rt, h), (rt * 1.02, h + 0.004), (0, h + 0.004)], rot, seg=14, label=(k.matte, 0.004, h), cell=cell)
        if kind != "drink":
            m.lathe(k.foil, (x, y, z + h + 0.003), [(0, 0), (rt * 1.05, 0), (rt * 1.05, 0.003), (0, 0.003)], rot, seg=14)
        else:
            m.lathe(k.foil, (x, y, z + h), [(0, 0), (rt * 0.9, 0), (rt * 0.9, 0.012), (0, 0.012)], rot, seg=10)
        return rt * 2, rt * 2

    def jar(self, x, y, z, yaw, tilt, cell):
        m, r, k = self.m, self.r, self.k; rr = r.uniform(0.03, 0.04); h = r.uniform(0.07, 0.1); rot = (tilt[0], tilt[1], yaw)
        m.lathe(k.glassb if r.random() < 0.3 else k.pet, (x, y, z), [(0, 0), (rr, 0), (rr, h), (0, h)], rot, seg=14, label=(k.matte, h * 0.3, h * 0.85), cell=cell)
        m.lathe(r.choice(k.liq[:5]), (x, y, z + 0.003), [(0, 0), (rr * 0.92, 0), (rr * 0.92, h * 0.8), (0, h * 0.8)], rot, seg=12, cap=False)
        m.lathe(k.foil if r.random() < 0.5 else self._cap(), (x, y, z + h), [(0, 0), (rr * 1.04, 0), (rr * 1.04, 0.015), (0, 0.015)], rot, seg=14)
        return rr * 2, rr * 2

    def deli(self, x, y, z, yaw, tilt, cell):
        m, r, k = self.m, self.r, self.k; w, d, h = r.uniform(0.12, 0.17), r.uniform(0.12, 0.16), r.uniform(0.045, 0.08); rot = (tilt[0], tilt[1], yaw)
        m.box(k.clear, (x, y, z + h / 2), (d, w, h), rot)
        m.box(r.choice((k.green, k.bread, k.cream, k.cheese)), (x, y, z + h * 0.38), (d * 0.9, w * 0.9, h * 0.55), rot)
        m.ellip(r.choice((k.green, k.choc, k.cream)), (x + 0.01, y, z + h * 0.62), (d * 0.38, w * 0.34, h * 0.28), rot, 0.004, r)
        m.box(k.matte, (x, y, z + h + 0.003), (d * 0.5, w * 0.7, 0.004), rot, cell=cell)
        return d, w

    def sandwich(self, x, y, z, yaw, tilt, cell):
        m, r, k = self.m, self.r, self.k; w, d, h = r.uniform(0.1, 0.13), r.uniform(0.15, 0.19), 0.05; rot = (tilt[0], tilt[1], yaw)
        m.box(k.bread, (x, y, z + 0.028), (d, w, 0.05), rot); m.box(k.green, (x, y, z + 0.032), (d * 0.97, w * 0.97, 0.01), rot)
        m.ellip(k.film, (x, y, z + 0.032), (d * 0.57, w * 0.56, 0.036), rot, 0.0015, r)
        m.box(k.matte, (x + d * 0.2, y, z + 0.052), (0.05, w * 0.7, 0.003), rot, cell=cell)
        return d, w

    def kimbap(self, x, y, z, yaw, tilt, cell):
        m, r, k = self.m, self.r, self.k; w, d = 0.1, 0.12; rot = (tilt[0], tilt[1], yaw)
        m.box(k.clear, (x, y, z + 0.03), (d, w, 0.06), rot)
        for q in range(4):
            m.lathe(k.rice, (x - d * 0.25 + q * d * 0.17, y, z + 0.032), [(0, 0), (0.024, 0), (0.024, 0.018), (0, 0.018)], (0, math.pi / 2, 0) if False else rot, seg=10)
            m.lathe(k.nori, (x - d * 0.25 + q * d * 0.17, y, z + 0.0325), [(0.0245, 0), (0.0245, 0.017)], rot, seg=10, cap=False)
        m.box(k.matte, (x, y, z + 0.063), (d * 0.5, w * 0.8, 0.003), rot, cell=cell)
        return d, w

    def onigiri(self, x, y, z, yaw, tilt, cell):
        m, r, k = self.m, self.r, self.k; s = r.uniform(0.085, 0.1); rot = (tilt[0], tilt[1], yaw)
        m.box(k.film, (x, y, z + 0.022), (s * 0.5, s, 0.045), rot); m.box(k.rice, (x, y, z + 0.022), (s * 0.45, s * 0.9, 0.04), rot)
        m.box(k.nori, (x - s * 0.18, y, z + 0.022), (s * 0.12, s * 0.7, 0.044), rot); m.box(k.matte, (x + s * 0.12, y, z + 0.048), (s * 0.2, s * 0.6, 0.003), rot, cell=cell)
        return s * 0.5, s

    def bag(self, x, y, z, yaw, tilt, cell, kind=None):
        m, r, k = self.m, self.r, self.k; kind = kind or r.choice(("bread", "salad")); rot = (tilt[0] + r.uniform(-0.1, 0.1), tilt[1], yaw)
        sx, sy, sz = r.uniform(0.085, 0.12), r.uniform(0.07, 0.1), r.uniform(0.04, 0.06)
        m.ellip(k.bag, (x, y, z + sz * 0.9), (sx, sy, sz), rot, 0.004, r); m.ellip(k.bread if kind == "bread" else k.green, (x, y, z + sz * 0.8), (sx * 0.85, sy * 0.85, sz * 0.75), rot, 0.003, r)
        m.box(k.film, (x + sx * 0.97, y, z + sz * 0.9), (0.03, sy * 1.0, 0.012), rot)                                    # the gathered, crimped end
        m.box(k.matte, (x + sx * 0.3, y, z + sz * 1.7), (0.06, sy * 0.8, 0.003), rot, cell=cell)
        return sx * 2, sy * 2

    def block(self, x, y, z, yaw, tilt, cell, kind=None):
        m, r, k = self.m, self.r, self.k; kind = kind or r.choice(("cheese", "butter")); rot = (tilt[0], tilt[1], yaw); w, d, h = r.uniform(0.07, 0.1), r.uniform(0.09, 0.12), r.uniform(0.03, 0.045)
        m.box(k.cheese if kind == "cheese" else k.butter, (x, y, z + h / 2), (d, w, h), rot); m.box(k.matte, (x, y, z + h / 2), (d + 0.002, w + 0.002, h * 0.9), rot, cell=cell)
        return d, w

    def cake(self, x, y, z, yaw, tilt, cell):
        m, r, k = self.m, self.r, self.k; rot = (tilt[0], tilt[1], yaw); w, d, h = 0.13, 0.15, 0.065
        m.box(k.clear, (x, y, z + h / 2), (d, w, h), rot)
        m.lathe(k.cream, (x, y, z + 0.004), [(0, 0), (0.05, 0), (0.05, 0.05), (0.04, 0.054), (0, 0.054)], rot, seg=14); m.lathe(k.choc, (x, y, z + 0.052), [(0, 0), (0.044, 0), (0.044, 0.01), (0, 0.01)], rot, seg=14)
        m.box(k.matte, (x - d / 2 - 0.001, y, z + h * 0.5), (0.002, w * 0.5, h * 0.4), rot, cell=cell)
        return d, w

    def dessert(self, x, y, z, yaw, tilt, cell):
        m, r, k = self.m, self.r, self.k; rr = r.uniform(0.035, 0.045); h = r.uniform(0.06, 0.08); rot = (tilt[0], tilt[1], yaw)
        m.lathe(k.pet, (x, y, z), [(0, 0), (rr * 0.7, 0), (rr, h), (0, h)], rot, seg=14)
        for q, (mt, hh) in enumerate(((k.choc, 0.35), (k.cream, 0.6), (k.cream, 0.8))):
            m.lathe(mt, (x, y, z + 0.004), [(0, 0), (rr * (0.72 + 0.28 * hh) * 0.95, 0), (rr * (0.72 + 0.28 * hh) * 0.95, h * hh * 0.5 + 0.004 * q), (0, h * hh * 0.5 + 0.004 * q)], rot, seg=12, cap=False) if q == 0 else None
        m.lathe(k.cream, (x, y, z + h * 0.8), [(0, 0), (rr * 0.9, 0), (rr * 0.9, 0.012), (0, 0.012)], rot, seg=12)
        m.lathe(k.foil, (x, y, z + h + 0.002), [(0, 0), (rr * 1.04, 0), (rr * 1.04, 0.003), (0, 0.003)], rot, seg=14)
        return rr * 2, rr * 2

    TYPES = {"drinks": ("bottle", "bottle", "can", "glass_bottle", "jug", "carton_brick"), "dairy": ("carton", "carton", "jug", "cup", "cup", "cup_drink", "block"),
             "meals": ("sandwich", "kimbap", "onigiri", "deli", "bag", "sandwich"), "dessert": ("cake", "dessert", "jar", "cup", "dessert"), "mix": ("bottle", "carton", "cup", "sandwich", "jar", "bag", "can", "block", "onigiri", "deli")}

    def place(self, kind, x, y, z, yaw, tilt, cell):
        return {"bottle": self.bottle, "can": self.can, "glass_bottle": self.glass_bottle, "carton": lambda *a: self.carton(*a, gable=True), "carton_brick": lambda *a: self.carton(*a, gable=False), "jug": self.jug,
                "cup": self.cup, "cup_drink": lambda *a: self.cup(*a, kind="drink"), "jar": self.jar, "deli": self.deli, "sandwich": self.sandwich, "kimbap": self.kimbap, "onigiri": self.onigiri, "bag": self.bag,
                "block": self.block, "cake": self.cake, "dessert": self.dessert}[kind](x, y, z, yaw, tilt, cell)


# ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
class OpenChillerFactory:
    LEN = None

    def __init__(self, seed):
        self.r = random.Random(seed)

    def spawn_asset(self, i):
        r = self.r; L = self.LEN or 1.8; D, H = 0.78, 2.0; k = Mats(); m = M()
        TH = 0.1                                                                                   # shelf slope (rad): the front edge is lower
        # --- body --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
        m.box(k.pc, (0.015, 0, H / 2), (0.03, L, H)); m.box(k.liner, (0.034, 0, 1.12), (0.006, L - 0.12, 1.65))
        for s in (1, -1):                                                                          # end panels: a metal frame round a glass pane
            yy = s * (L / 2 - 0.015)
            m.box(k.pc, (D / 2, yy, 0.12), (D, 0.03, 0.24)); m.box(k.pc, (D / 2, yy, H - 0.16), (D, 0.03, 0.32)); m.box(k.pc, (0.04, yy, H / 2), (0.08, 0.03, H)); m.box(k.pc, (D - 0.04, yy, H / 2), (0.08, 0.03, H))
            m.box(k.sglass, (D / 2, yy, 1.12), (D - 0.14, 0.008, 1.55))
        m.box(k.pc, (D / 2, 0, 0.1), (D, L, 0.2)); m.box(k.pc, (D / 2 + 0.03, 0, H - 0.16), (D + 0.06, L, 0.32))                      # plinth and canopy
        for q in range(int(0.15 / 0.022)):                                                         # the louvred intake grille on the kick plate
            m.box(k.pc, (D + 0.004, 0, 0.04 + q * 0.022), (0.012, L - 0.12, 0.012), (0, 0.5, 0))
        m.box(k.ink, (D - 0.005, 0, 0.1), (0.004, L - 0.1, 0.16))
        m.box(k.sign, (D + 0.062, 0, H - 0.16), (0.006, L * 0.8, 0.22)); cx = -L * 0.3                                  # the backlit sign panel with an abstract wordmark
        while cx < L * 0.3:
            gw = r.uniform(0.03, 0.07); m.box(k.ink, (D + 0.067, cx + gw / 2, H - 0.16 + r.uniform(-0.01, 0.01)), (0.003, gw, r.uniform(0.06, 0.11))); cx += gw + r.uniform(0.012, 0.03)
        m.box(k.pc, (D - 0.02, -L / 2 + 0.06, H / 2), (0.012, 0.03, H - 0.4)); m.box(k.ink, (0.05, L / 2 - 0.05, H / 2), (0.05, 0.03, H - 0.3))                  # a cable duct on the end
        for q in range(6):
            m.lathe(k.steel, (0.075, L / 2 - 0.05, 0.3 + q * 0.28), [(0, 0), (0.008, 0), (0.008, 0.006), (0, 0.006)], (0, math.pi / 2, 0), seg=6)
        zs = [0.28, 0.62, 0.96, 1.3, 1.64]; n_slots = int((L - 0.2) / 0.07)
        for z in zs[1:] + [H - 0.34]:                                                              # air-return / discharge slot rows in the liner
            for q in range(n_slots):
                m.box(k.ink, (0.038, -(L - 0.2) / 2 + 0.035 + q * 0.07, z + 0.27), (0.004, 0.045, 0.012))
        lights = []
        # --- shelves -----------------------------------------------------------------------------------------------------------------------------------------------------------------------------
        for si, z in enumerate(zs):
            m.box(k.steel, (D / 2 - 0.05, 0, z), (D - 0.12, L - 0.07, 0.012), (0, TH, 0)); m.box(k.steel, (D - 0.07, 0, z - 0.012), (0.012, L - 0.07, 0.06), (0, 0.35, 0))      # tray + folded front lip
            m.box(k.rail, (D - 0.056, 0, z - 0.016), (0.014, L - 0.1, 0.034))                       # the price rail
            tx = -(L - 0.2) / 2 + 0.06
            while tx < (L - 0.2) / 2 - 0.05:
                w = r.uniform(0.07, 0.11); m.box(k.tag, (D - 0.0475, tx, z - 0.016), (0.003, w, 0.026), cell=r.randrange(100)); tx += w + r.uniform(0.01, 0.1)
            for s in (1, -1):
                m.box(k.steel, (D / 2, s * (L / 2 - 0.045), z - 0.03), (D - 0.14, 0.012, 0.03))      # shelf support brackets
            ztop = zs[si + 1] if si + 1 < len(zs) else H - 0.34
            m.box(k.led, (D - 0.1, 0, ztop - 0.045), (0.028, L - 0.14, 0.01))                         # the LED strip at the front of the shelf above (lights this shelf's goods)
            lo = bpy.data.lights.new(f"ir_oc2_led_{si}", "AREA"); lo.shape = "RECTANGLE"; lo.size = L - 0.2; lo.size_y = 0.12; lo.energy = 14.0; lo.color = (0.86, 0.94, 1.0); lo.spread = math.radians(130)
            lights.append((lo, (D - 0.14, 0.0, ztop - 0.06)))
        # --- stock, shelf by shelf, as facings with controlled disorder ----------------------------------------------------------------------------------------------------------------------------------
        st = Stock(m, k, r); themes = ["drinks", "dairy", "meals", "dessert", "mix"]; r.shuffle(themes)
        for si, z in enumerate(zs):
            theme = themes[si % len(themes)]; kinds = Stock.TYPES[theme]
            y = -L / 2 + 0.1; limit = L / 2 - 0.1 - (r.uniform(0.2, 0.55) * L if r.random() < 0.08 else 0.0)                       # 8 % of shelves are half empty
            n_f = 0
            while y < limit:
                if r.random() < 0.08:
                    y += r.uniform(0.04, 0.12); continue                                           # a gap where products were taken
                kind = r.choice(kinds) if r.random() < 0.9 else r.choice(sum(Stock.TYPES.values(), ()))                          # one facing in ten is a misplaced product
                cell = r.randrange(100); across = r.choice((1, 2, 2, 3, 3)); deep = r.choice((2, 2, 3, 3)); wmax = 0.0; xfront = D - 0.12
                for a in range(across):
                    d_used = 0.0; dyy = 0.0
                    for dp in range(deep):
                        yaw = r.uniform(-0.09, 0.09) * (1.0 if dp == 0 else 0.5)                    # +-5 deg
                        xo = xfront - r.uniform(0.0, 0.025) - d_used - 0.045 + (0.0 if dp else r.uniform(0.0, 0.03))             # pulled forward / back
                        zz = z + 0.007 - (xo - (D / 2 - 0.05)) * math.tan(TH)
                        yo = y + a * (0.075 if kind in ("bottle", "can", "cup", "jar", "dessert", "glass_bottle") else 0.12) + r.uniform(-0.012, 0.012)
                        if yo > L / 2 - 0.08:
                            break
                        d, w = st.place(kind, xo, yo, zz, yaw, (0.0, TH, 0.0) if False else (0.0, TH, 0.0), cell); d_used += d + 0.012; wmax = max(wmax, w + a * 0.08)
                        if xo - d_used < 0.1:
                            break
                y += max(wmax, 0.06) + r.uniform(0.004, 0.02); n_f += 1
                if kind in ("bottle", "can", "carton", "jug") and r.random() < 0.12:                    # a clear plastic shelf stopper between facings
                    m.box(k.clear, (D / 2 - 0.1, y - 0.004, z + 0.04 - (D / 2 - 0.15 - (D / 2 - 0.05)) * math.tan(TH)), (D - 0.3, 0.004, 0.08), (0, TH, 0))
            if r.random() < 0.55:                                                                  # one product knocked over / lying at the front
                st.place(r.choice(("bottle", "carton", "can", "cup", "sandwich")), D - 0.15, r.uniform(-L / 2 + 0.15, L / 2 - 0.15), z + 0.034, r.uniform(0, 6.28), (r.choice((1.45, -1.45)), TH, 0.0), r.randrange(100))
        o = m.object(f"OpenChillerFactory({i}).spawn_asset({i})")
        md = o.modifiers.new("ir_bevel", "BEVEL"); md.width = 0.0015; md.segments = 2; md.limit_method = "ANGLE"; md.angle_limit = math.radians(40)       # sheet-metal radius on every edge
        wn = o.modifiers.new("ir_wn", "WEIGHTED_NORMAL"); wn.keep_sharp = True
        for lo, loc in lights:
            ob = bpy.data.objects.new(f"AreaLampFactory(chiller).spawn_asset({i}_{lo.name})", lo); bpy.context.scene.collection.objects.link(ob); ob.parent = o; ob.location = loc; ob.rotation_euler = (math.pi, 0, 0)
        return o
