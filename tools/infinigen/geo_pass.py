"""Global bevel + smooth-shading pass for procedural props (realism program P2: 'edges are razor-sharp with no bevels anywhere, ducts are faceted'). Hooked from kit_lighting (last geometry pass), only when ROOM_GEO_PASS=1.

  bevel   a Bevel modifier (width = 4 % of the object's smallest dimension, clamped to 1..3 mm, 2 segments, limit by 30 deg angle) on every procedural prop whose name matches KEYS (desks, cabinets, partitions, doors / casings,
          beds, TVs, cassettes, counters, tables, shelves, racks, lockers, vanities ...) and whose mesh has <= ROOM_GEO_MAXPOLY (default 4000) polygons: Infinigen's own organic models are skipped, so the poly budget stays small
          (the modifier is evaluated at render time; nothing is applied to the mesh).
  ducts   Duct / Pipe / Cylinder-like objects (names Duct, Pipe, Conduit): smooth shading + an Edge Split at 35 deg so the rings read round, and a galvanized-metal look (roughness ~0.3, metallic 0.8 when the material is a flat Principled).
Idempotent (a modifier is added once). ROOM_GEO_BEVEL_MAX (m, default 0.003) caps the width."""
from __future__ import annotations

import os

import bpy

KEYS = ("Desk", "Cabinet", "Partition", "Door", "Casing", "Bed", "TV", "Display", "Cassette", "Counter", "Table", "Shelf", "Rack", "Locker", "Vanity", "Wardrobe", "Credenza", "Bookcase", "Bench",
        "Workbench", "Reception", "Sideboard", "Cooler", "Chiller", "Stand", "Dresser", "Nightstand", "Platform", "Pedestal", "Kitchen", "Fridge", "Island")
SKIP = ("Bottle", "Jar", "Cup", "Plant", "Tree", "Leaf", "Rug", "Curtain", "Wine", "Book", "Cloth", "Pillow", "Cushion", "Baseboard", "Skirting", "Light", "Lamp", "Sprinkler")
DUCTS = ("Duct", "Pipe", "Conduit")


def apply(stats):
    if os.environ.get("ROOM_GEO_SOFT") == "1":
        soft(stats)
    if os.environ.get("ROOM_GEO_PASS") != "1":
        return 0
    cap = float(os.environ.get("ROOM_GEO_BEVEL_MAX") or 0.003); maxp = int(os.environ.get("ROOM_GEO_MAXPOLY") or 4000)
    nb = nd = 0
    for o in bpy.data.objects:
        if o.type != "MESH":
            continue
        n = o.name.split("(")[0]
        if any(k in n for k in DUCTS):
            if not any(md.type == "EDGE_SPLIT" for md in o.modifiers):
                for p in o.data.polygons:
                    p.use_smooth = True
                md = o.modifiers.new("ir_duct_split", "EDGE_SPLIT"); md.split_angle = 0.61; md.use_edge_angle = True; md.use_edge_sharp = False
                for sl in o.material_slots:
                    b = next((x for x in sl.material.node_tree.nodes if x.type == "BSDF_PRINCIPLED"), None) if (sl.material and sl.material.use_nodes) else None
                    if b is not None and not b.inputs["Roughness"].is_linked and not b.inputs["Base Color"].is_linked:
                        b.inputs["Roughness"].default_value = 0.3; b.inputs["Metallic"].default_value = max(b.inputs["Metallic"].default_value, 0.8)
                nd += 1
            continue
        if not any(k in n for k in KEYS) or any(k in n for k in SKIP) or o.get("ir_geo") or len(o.data.polygons) > maxp or len(o.data.polygons) < 6:
            continue
        if any(md.type == "BEVEL" for md in o.modifiers):
            continue
        dm = [d for d in o.dimensions if d > 1e-4]
        if not dm:
            continue
        w = max(0.001, min(cap, 0.04 * min(dm)))
        md = o.modifiers.new("ir_geo_bevel", "BEVEL"); md.width = w; md.segments = 2; md.limit_method = "ANGLE"; md.angle_limit = 0.52
        o["ir_geo"] = 1; nb += 1
    stats["geo_pass"] = {"bevelled": nb, "ducts": nd}
    return nb + nd


SOFT = ("Loveseat", "Sofa", "SoftBed", "Armchair", "Pouf", "Ottoman", "Headboard")


def soft(stats):
    """ROOM_GEO_SOFT=1 (H3 external review: 'the white upholstered headboard / loveseat is very smooth and boxy'): a Subdivision modifier (level 1, render 1) with creased edges kept by a prior bevel, on soft furniture with <= 8,000
    polygons; its fabric slots get a fine weave bump (Principled normal, a brick-less noise at 400 / m stretched along the warp, strength 0.15) and sheen 0.3 / sheen roughness 0.5. Idempotent."""
    n = nm = 0
    seen = set()
    for o in bpy.data.objects:
        if o.type != "MESH" or not any(k in o.name.split("(")[0] for k in SOFT) or o.get("ir_soft") or len(o.data.polygons) > 8000:
            continue
        if not any(md.type == "SUBSURF" for md in o.modifiers):
            if not any(md.type == "BEVEL" for md in o.modifiers):
                bv = o.modifiers.new("ir_soft_bevel", "BEVEL"); bv.width = 0.012; bv.segments = 3; bv.limit_method = "ANGLE"; bv.angle_limit = 0.52
            sd = o.modifiers.new("ir_soft_subd", "SUBSURF"); sd.levels = 1; sd.render_levels = 1
        o["ir_soft"] = 1; n += 1
        for sl in o.material_slots:
            m = sl.material
            if m is None or not m.use_nodes or m.name in seen or m.get("ir_weave"):
                continue
            seen.add(m.name)
            b = next((x for x in m.node_tree.nodes if x.type == "BSDF_PRINCIPLED"), None)
            if b is None or b.inputs["Metallic"].default_value > 0.3 or b.inputs["Transmission Weight"].default_value > 0.2:
                continue
            N, L = m.node_tree.nodes, m.node_tree.links
            tc = N.new("ShaderNodeTexCoord"); mp = N.new("ShaderNodeMapping"); mp.inputs["Scale"].default_value = (400.0, 400.0, 400.0); L.new(tc.outputs["Object"], mp.inputs["Vector"])
            wv = N.new("ShaderNodeTexChecker"); wv.inputs["Scale"].default_value = 1.0; L.new(mp.outputs["Vector"], wv.inputs["Vector"])
            bp = N.new("ShaderNodeBump"); bp.inputs["Strength"].default_value = 0.15; bp.inputs["Distance"].default_value = 0.0004; L.new(wv.outputs["Fac"], bp.inputs["Height"])
            if b.inputs["Normal"].is_linked:
                L.new(b.inputs["Normal"].links[0].from_socket, bp.inputs["Normal"])
            L.new(bp.outputs["Normal"], b.inputs["Normal"])
            if "Sheen Weight" in b.inputs:
                b.inputs["Sheen Weight"].default_value = 0.3; b.inputs["Sheen Roughness"].default_value = 0.5
            m["ir_weave"] = True; nm += 1
    stats["geo_soft"] = {"objects": n, "materials": nm}
    return n
