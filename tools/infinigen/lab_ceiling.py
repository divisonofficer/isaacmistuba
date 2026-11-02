"""Exposed service ceiling of the research-building corridor (floor N; ref out/room_planner_refs/lab_corridor_0127_clean 01, 05, 07). Hooked from kit_lighting after hung_lights,
only when ROOM_LAB_CEILING=1.

    from lab_ceiling import apply; stats["lab_ceiling"] = apply(stats)

For every room named hallway*: removes ceiling fixtures (track lights, grid, tubes) above 2.2 m, then builds, along the corridor's long axis: orange cross beams every 1.5 m
(0.1 x width x 0.22), four service pipes (blue / yellow / grey / white, r 0.035-0.07) hung under them at different heights and lateral offsets, small brackets, and a row of warm fluorescent
tubes (1.2 m, emissive, with an area light each) every 2.4 m. A red hanging sign (0.35 x 0.12) near the far end. Lab rooms and the lobby are untouched.
"""
from __future__ import annotations

import math
import os

import bmesh
import bpy
from mathutils import Vector

import room_dressing as rd
from room_planner import proc_assets as pa

REMOVE = ("CeilingGridFactory", "LinearLedFactory", "DiffuserFactory", "AcCassetteFactory", "SprinklerFactory")


def _obj(name, mat_prims):
    bm = bmesh.new(); mats = []
    for slot, (mat, prims) in enumerate(mat_prims):
        mats.append(mat)
        for p in prims:
            if p[0] == "box":
                _, c, sz = p
                r = bmesh.ops.create_cube(bm, size=1.0); bmesh.ops.scale(bm, vec=sz, verts=r["verts"]); bmesh.ops.translate(bm, vec=c, verts=r["verts"])
            else:                                                   # ("cyl", centre, radius, length, axis 0=x 1=y)
                _, c, rad, ln, ax = p
                r = bmesh.ops.create_cone(bm, cap_ends=True, segments=10, radius1=rad, radius2=rad, depth=ln)
                bmesh.ops.rotate(bm, cent=(0, 0, 0), matrix=__import__("mathutils").Matrix.Rotation(math.pi / 2, 3, "Y" if ax == 0 else "X"), verts=r["verts"])
                bmesh.ops.translate(bm, vec=c, verts=r["verts"])
            for f in {f for v in r["verts"] for f in v.link_faces}:
                f.material_index = slot
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    for m in mats:
        me.materials.append(m)
    o = bpy.data.objects.new(name, me); bpy.context.scene.collection.objects.link(o)
    return o


def _emit(name, rgb, strength):
    m = pa._flat(name, rgb, 0.4); b = m.node_tree.nodes["Principled BSDF"]
    b.inputs["Emission Color"].default_value = (*rgb, 1.0); b.inputs["Emission Strength"].default_value = strength
    return m


def _bare(name, rgb, rough, amp=0.0):
    """Unpainted metal: metallic exactly 1, optional roughness noise (galvanized spangle / brushed streaks) of +-amp."""
    m = pa._flat(name, rgb, rough, 1.0)
    if amp > 0 and not m.get("bare_noise"):
        nt = m.node_tree; N, Lk = nt.nodes, nt.links; b = N["Principled BSDF"]
        tc = N.new("ShaderNodeTexCoord"); nz = N.new("ShaderNodeTexNoise"); nz.inputs["Scale"].default_value = 45.0; nz.inputs["Detail"].default_value = 3.0
        mr = N.new("ShaderNodeMapRange"); mr.inputs["To Min"].default_value = max(0.05, rough - amp); mr.inputs["To Max"].default_value = rough + amp
        Lk.new(tc.outputs["Object"], nz.inputs["Vector"]); Lk.new(nz.outputs["Fac"], mr.inputs["Value"]); Lk.new(mr.outputs["Result"], b.inputs["Roughness"])
        m["bare_noise"] = True
    return m


def apply(stats):
    if os.environ.get("ROOM_LAB_CEILING") != "1":
        return 0
    RIG = os.environ.get("ROOM_LAB_RIG") == "1"       # N2 r15 review vs ref: blown-out white, flat. RIG = saturated rust beams / blue + yellow pipes, a dark slab, FEWER brighter bare tubes, little fill
    BARE = os.environ.get("ROOM_LAB_BARE_METAL") == "1"   # unpainted runs (metallic exactly 1) beside the painted ones (metallic exactly 0): galvanized spiral duct, stainless + copper pipes, galvanized unistrut brackets
    beam = pa._flat("ir_lab_beam", (0.45, 0.12, 0.04) if RIG else (0.78, 0.36, 0.12), 0.5, 0.2)
    pipes = [pa._flat(f"ir_lab_pipe_{k}", c, 0.4, 0.3) for k, c in enumerate(((0.03, 0.12, 0.40), (0.60, 0.42, 0.03), (0.5, 0.52, 0.55), (0.88, 0.88, 0.86)) if RIG else ((0.12, 0.3, 0.75), (0.85, 0.7, 0.12), (0.5, 0.52, 0.55), (0.88, 0.88, 0.86)))]
    if BARE:                                                                  # run 2 (grey) -> galvanized spiral duct, extra copper + stainless runs; the rest stay painted (metallic 0)
        pipes[2] = _bare("ir_lab_galv_duct", (0.66, 0.68, 0.7), 0.35, 0.12)
        pipes += [_bare("ir_lab_copper", (0.95, 0.64, 0.54), 0.3, 0.06), _bare("ir_lab_stainless", (0.75, 0.76, 0.78), 0.2, 0.05)]
    fill = float(os.environ.get("ROOM_LAB_FILL", "1.0")); world_k = float(os.environ.get("ROOM_LAB_WORLD", "1.0")) if RIG else 1.0
    if RIG and world_k != 1.0 and bpy.context.scene.world and bpy.context.scene.world.use_nodes:
        for n_ in bpy.context.scene.world.node_tree.nodes:
            if n_.type == "BACKGROUND":
                n_.inputs["Strength"].default_value *= world_k
    black = _bare("ir_lab_unistrut", (0.62, 0.64, 0.66), 0.35, 0.08) if BARE else pa._flat("ir_lab_bracket", (0.05, 0.05, 0.055), 0.5, 0.6); tube = _emit("ir_lab_tube", (1.0, 0.9, 0.72), 30.0 if RIG else 14.0); red = _emit("ir_lab_sign", (0.9, 0.12, 0.08), 3.0)
    done = 0
    prefixes = tuple(x.strip() for x in (os.environ.get("ROOM_LAB_CEILING_ROOMS") or "hallway").split(",") if x.strip())     # N2: also the laboratories (utility cells >= 30 m2): ROOM_LAB_CEILING_ROOMS=hallway,utility
    for name, parts in rd._rooms().items():
        if not name.startswith(prefixes) or "floor" not in parts or "wall" not in parts:
            continue
        if not name.startswith("hallway"):
            _b = [parts["floor"].matrix_world @ Vector(c_) for c_ in parts["floor"].bound_box]
            if (max(q.x for q in _b) - min(q.x for q in _b)) * (max(q.y for q in _b) - min(q.y for q in _b)) < 30.0:
                continue
        fp = [parts["floor"].matrix_world @ Vector(c) for c in parts["floor"].bound_box]; wp = [parts["wall"].matrix_world @ Vector(c) for c in parts["wall"].bound_box]
        x0, x1, y0, y1 = min(p.x for p in fp), max(p.x for p in fp), min(p.y for p in fp), max(p.y for p in fp)
        fz, zc = max(p.z for p in fp), max(p.z for p in wp)
        along_x = (x1 - x0) >= (y1 - y0); L = (x1 - x0) if along_x else (y1 - y0); Wd = (y1 - y0) if along_x else (x1 - x0)
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        removed = 0
        for o in list(bpy.data.objects):
            t = o.matrix_world.translation
            if not (x0 - 0.2 <= t.x <= x1 + 0.2 and y0 - 0.2 <= t.y <= y1 + 0.2) or t.z < fz + 2.2 or o.name.endswith((".ceiling", ".wall", ".exterior")):
                continue
            base = o.name.split("(")[0]
            if base in REMOVE or o.type == "LIGHT" or "Track" in base or "LampFactory" in base or "CeilingLight" in base or (o.type == "MESH" and "Ceiling" in base):
                bpy.data.objects.remove(o, do_unlink=True); removed += 1
        if RIG:
            for o in bpy.data.objects:                           # the generic fixtures / fill lights in this room carry less: the tubes are the light
                if o.type == "LIGHT" and not o.name.startswith("PointLampFactory(lab)") and "window" not in o.name.lower():
                    t = o.matrix_world.translation
                    if x0 - 0.2 <= t.x <= x1 + 0.2 and y0 - 0.2 <= t.y <= y1 + 0.2:
                        o.data.energy *= fill
            cm = bpy.data.objects.get(f"{name}.ceiling")
            if cm is not None and cm.type == "MESH":
                for sl in cm.material_slots:
                    if sl.material is not None and sl.material.use_nodes and "Principled BSDF" in sl.material.node_tree.nodes and not sl.material.get("lab_dark"):
                        sl.material = sl.material.copy(); sl.material["lab_dark"] = True
                        bb_ = sl.material.node_tree.nodes["Principled BSDF"]
                        for l_ in list(bb_.inputs["Base Color"].links):
                            sl.material.node_tree.links.remove(l_)
                        bb_.inputs["Base Color"].default_value = (0.03, 0.028, 0.026, 1)
        loc = lambda u, v, z: ((x0 + u, cy + v, z) if along_x else (cx + v, y0 + u, z))           # u along the corridor from its start, v across from the centre
        sz = lambda su, sv, sw: ((su, sv, sw) if along_x else (sv, su, sw))
        bm_p, pipe_p, br_p = [], [[] for _ in range(6 if BARE else 4)], []
        n_beam = max(2, int(L / 1.5))
        for k in range(n_beam):
            u = (k + 0.5) * L / n_beam
            bm_p.append(("box", loc(u, 0, zc - 0.11), sz(0.1, Wd - 0.1, 0.22)))
        runs_ = [(-0.75, 0.30, 0.07), (-0.25, 0.42, 0.05), (0.3, 0.30, 0.07 if BARE else 0.04), (0.78, 0.40, 0.06)] + ([(-0.52, 0.50, 0.025), (0.55, 0.47, 0.03)] if BARE else [])
        for pi_, (v, dz, rad) in enumerate(runs_):
            c = loc(L / 2, v, zc - dz)
            pipe_p[pi_].append(("cyl", c, rad, L - 0.2, 0 if along_x else 1))
            for k in range(n_beam):
                u = (k + 0.5) * L / n_beam
                br_p.append(("box", loc(u, v, zc - dz / 2 - 0.02), sz(0.03, 0.03, dz - 0.04)))
        _obj(f"LabCeilingFactory({name}).spawn_asset(beams)", [(beam, bm_p), (black, br_p)] + [(pipes[i], pipe_p[i]) for i in range(len(pipe_p))])
        tubes, n_t = [], 0
        pitch = 3.6 if RIG else 2.4
        for k in range(int(L / pitch)):
            u = 1.2 + k * pitch
            if u > L - 0.8:
                break
            for v in (-0.35, 0.4):
                tubes.append(("box", loc(u, v, zc - 0.28), sz(1.2, 0.07, 0.04)))
            ld = bpy.data.lights.new(f"ir_lab_tube_{name}_{k}", "AREA"); ld.shape = "RECTANGLE"; ld.spread = math.radians(100) if RIG else math.pi; ld.size = 1.2; ld.size_y = 0.6; ld.energy = 160.0 if RIG else 55.0; ld.color = (1.0, 0.86, 0.66) if RIG else (1.0, 0.9, 0.74)
            lo = bpy.data.objects.new(f"PointLampFactory(lab).spawn_asset({name}_{k})", ld); bpy.context.scene.collection.objects.link(lo)
            lo.location = loc(u, 0.0, zc - 0.34); lo.rotation_euler = (math.pi, 0, 0 if along_x else math.pi / 2); n_t += 1
        sign = [("box", loc(L - 1.6, 0.6, zc - 0.55), sz(0.35, 0.03, 0.12))]
        _obj(f"LabCeilingFactory({name}).spawn_asset(tubes)", [(tube, tubes), (red, sign)])
        print(f"LAB_CEILING {name} removed={removed} beams={n_beam} tubes={n_t} length={L:.1f} width={Wd:.1f}", flush=True)
        done += 1
    stats["lab_ceiling"] = done
    return done
