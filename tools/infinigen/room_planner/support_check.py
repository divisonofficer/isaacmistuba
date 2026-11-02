"""Support check for floor-standing furniture (user 10-23, S34 r16: 'a chair floats above the glass railing'). Runs at the end of realize(): for every top-level chair / stool / table / desk / sofa / plant / floor lamp,
ray-cast straight down from under its lowest point at the footprint centre and four inset corners. If the nearest support is more than 2 cm below:
  - the surface is a floor / platform / rug  ->  snap the object down onto it ("snapped");
  - the surface is anything else (a railing, glass, partition, another object's top) or there is none  ->  delete it ("dropped").
Every case prints  [support] floating <name> at (x,y) gap Z cm -> snapped|dropped  and counts into stats["floating_snapped"], stats["floating_dropped"]; the round's totals print as  [support] N snapped, M dropped.
ROOM_SUPPORT_CHECK=0 turns it off; ROOM_SUPPORT_GAP = tolerance in m (default 0.02).
"""
from __future__ import annotations

import os

import bpy
from mathutils import Vector

KINDS = ("chair", "stool", "table", "desk", "sofa", "armchair", "loveseat", "bench", "plant", "pottedplant", "floorlamp", "pouf", "bed")
OK_SURFACE = ("floor", "platform", "rug", "carpet", "stage", "podium", "terrace", "balcony")


def _top_objects():
    return [o for o in bpy.data.objects if o.type == "MESH" and o.parent is None and not o.hide_render]


def _is_target(o):
    n = o.name.lower()
    if not any(k in n for k in KINDS) or any(k in n for k in ("wall", "ceiling", "pendant", "wallshelf", "wallgondola", "wall_")):
        return False
    return not o.get("ir_wall_mounted")


def _bbox(o):
    pts = [o.matrix_world @ Vector(c) for o in [o, *o.children_recursive] if o.type == "MESH" for c in o.bound_box]
    return (min(p.x for p in pts), max(p.x for p in pts), min(p.y for p in pts), max(p.y for p in pts), min(p.z for p in pts), max(p.z for p in pts))


def apply(stats):
    books(stats)
    appliances(stats)
    if os.environ.get("ROOM_SUPPORT_CHECK") == "0":
        return {}
    tol = float(os.environ.get("ROOM_SUPPORT_GAP") or 0.02)
    sc = bpy.context.scene; bpy.context.view_layer.update(); dg = bpy.context.evaluated_depsgraph_get()
    snapped = dropped = 0
    for o in _top_objects():
        if not _is_target(o):
            continue
        x0, x1, y0, y1, zmin, zmax = _bbox(o)
        if zmax - zmin < 0.05 or zmin > 1.5:                       # thin things and anything meant to hang up high are not floor furniture
            continue
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2; ix, iy = (x1 - x0) * 0.3, (y1 - y0) * 0.3
        best = None
        for px, py in ((cx, cy), (cx - ix, cy - iy), (cx + ix, cy - iy), (cx - ix, cy + iy), (cx + ix, cy + iy)):
            org = Vector((px, py, zmin + 0.005)); found = None
            for _ in range(8):                                     # skip the object's own faces (legs, seat); a hit on a downward face means we started inside a solid (a floor slab the legs touch): supported
                hit, loc, nrm, _, ho, _ = sc.ray_cast(dg, org, Vector((0, 0, -1)), distance=4.0)
                if not hit:
                    break
                if ho is o or ho.parent is o or (ho.parent is not None and ho.parent.parent is o):
                    org = Vector((loc.x, loc.y, loc.z - 1e-4)); continue
                found = (0.0 if nrm.z < 0 else max(zmin - loc.z, 0.0), ho); break
            if found is None:
                found = (9.9, None) if best is None else None
            if found is not None and (best is None or found[0] < best[0]):
                best = found
        if best is None or best[0] <= tol:
            continue
        gap, ho = best
        ok = ho is not None and any(k in ho.name.lower() for k in OK_SURFACE) and not any(k in ho.name.lower() for k in ("rail", "glass", "partition"))
        if ok and gap < 1.5:
            o.location.z -= gap - 0.001; snapped += 1; verdict = "snapped"
        else:
            for c in list(o.children_recursive):
                bpy.data.objects.remove(c, do_unlink=True)
            bpy.data.objects.remove(o, do_unlink=True); dropped += 1; verdict = "dropped"
        print(f"[support] floating {o.name if verdict == 'snapped' else '(removed)'} at ({cx:.2f},{cy:.2f}) gap {gap * 100:.0f} cm over {ho.name if ho else 'nothing'} -> {verdict}", flush=True)
    stats["floating_snapped"] = stats.get("floating_snapped", 0) + snapped; stats["floating_dropped"] = stats.get("floating_dropped", 0) + dropped
    print(f"[support] {snapped} snapped, {dropped} dropped", flush=True)
    return {"snapped": snapped, "dropped": dropped}


SOFT_HOSTS = ("bed", "sofa", "loveseat", "armchair", "pouf", "cushion", "blanket", "pillow", "duvet", "mattress")


def books(stats):
    """P2b r34 ('a colourless book stands upright on its edge on the bed'): a single Book / Notebook / Magazine whose broad face is not horizontal and which rests on a soft surface (bed, sofa, armchair, pouf, cushion,
    blanket) is laid flat: tilts reset (yaw kept), bottom re-seated on the support under it (a ray from above its centre). Books on shelves / desks are left alone. ROOM_BOOK_FLAT=0 turns it off."""
    if os.environ.get("ROOM_BOOK_FLAT") == "0":
        return 0
    scene = bpy.context.scene; deps = bpy.context.evaluated_depsgraph_get(); n = 0
    for o in _top_objects():
        nm = o.name.split("(")[0]
        if not nm.startswith(("Book", "Notebook", "Magazine")) or nm.startswith("BookStack") or nm.startswith("BookColumn"):
            continue
        q = [o.matrix_world @ Vector(c) for c in o.bound_box]; zext = max(v.z for v in q) - min(v.z for v in q); thin = min(o.dimensions)
        if zext < max(0.06, 3.0 * thin):
            continue                                                         # already (nearly) flat
        c = sum(q, Vector()) / 8; top = max(v.z for v in q)
        hit = scene.ray_cast(deps, Vector((c.x, c.y, min(v.z for v in q) - 0.002)), Vector((0, 0, -1)), distance=0.6)           # from just under the book: a ray from above would hit the book itself
        if not hit[0] or "room" in hit[4].name.lower() or not any(k in hit[4].name.lower() for k in SOFT_HOSTS):         # "bedroom_0/2.floor" contains "bed"
            continue
        z0 = hit[1].z
        o.rotation_mode = "XYZ"; o.rotation_euler = (0.0, 0.0, o.rotation_euler[2]); bpy.context.view_layer.update()
        q = [o.matrix_world @ Vector(c_) for c_ in o.bound_box]; o.location.z += z0 - min(v.z for v in q) + 0.002
        print(f"[support] book {o.name} laid flat on {hit[4].name}", flush=True); n += 1
    stats["books_flattened"] = n
    return n


APPL = ("Microwave", "EspressoMachine", "Toaster", "Kettle", "Grinder", "CoffeeMachine", "Blender", "RiceCooker", "WaterDispenser")
TOPS = ("counter", "island", "desk", "table", "cabinet", "shelf", "sideboard", "pantry", "run", "backbar", "vanity", "fridge", "dresser")


def appliances(stats):
    """O4 (user 10-24: 'a floating microwave on the wall above the cafe counter'): a small appliance whose bottom is more than 5 cm above the nearest support below it, and that has none of the support names TOPS underneath
    within 1.2 m (so no counter / cabinet to stand on), is dropped; one over a counter-like support (gap > 5 cm, <= 1.2 m) is lowered onto it. A hit on the floor means it is hanging in the air: deleted. ROOM_APPLIANCE_CHECK=0 off."""
    if os.environ.get("ROOM_APPLIANCE_CHECK") == "0":
        return 0
    scene = bpy.context.scene; deps = bpy.context.evaluated_depsgraph_get(); low = gone = 0
    for o in _top_objects():
        if not o.name.split("(")[0].startswith(APPL):
            continue
        q = [o.matrix_world @ Vector(c) for c in o.bound_box]; zb = min(v.z for v in q); c = sum(q, Vector()) / 8
        best = None
        for px, py in ((c.x, c.y), (c.x - 0.1, c.y), (c.x + 0.1, c.y), (c.x, c.y - 0.1), (c.x, c.y + 0.1)):
            h = scene.ray_cast(deps, Vector((px, py, zb - 0.003)), Vector((0, 0, -1)), distance=2.0)
            if h[0] and (best is None or h[1].z > best[1].z):
                best = h
        if best is None:
            continue
        gap = zb - best[1].z; nm = best[4].name.lower()
        if gap <= 0.05:
            continue
        if any(k in nm for k in TOPS) and gap <= 1.2:
            o.location.z -= gap - 0.002; low += 1; print(f"[support] appliance {o.name} lowered {gap:.2f} m onto {best[4].name}", flush=True)
        else:
            print(f"[support] appliance {o.name} floating {gap:.2f} m over {best[4].name} -> dropped", flush=True); bpy.data.objects.remove(o, do_unlink=True); gone += 1
    stats["appliances_lowered"] = low; stats["appliances_dropped"] = gone
    return low + gone
