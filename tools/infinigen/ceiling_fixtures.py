"""Home-like ceiling fixtures for Infinigen apartments (user 2026-10-15: "천장에 집 다운 조명").

Infinigen puts the same 23 cm puck (CeilingLightFactory, one factory seed per house) on every ceiling, each with a point light child.
This swaps each puck for an ABO product fixture chosen by room type, one model per room (a household buys one per room):

  dining-room  a pendant or chandelier over the dining table (the light nearest the table moves there)
  living-room  chandelier (40%) or flush mount     kitchen  pendant over an island, else flush
  bedroom      flush mount                         other    flush mount

The canopy sits against the ceiling. A hanging fixture keeps 2.05 m of headroom, or 0.7 m above the table it hangs over; a model
that does not fit falls back to a flush mount. The puck's point light (same energy: the adapter writes ir_rgb_energy_w from it) moves
2 cm under the new fixture's bottom, so an opaque shade does not swallow it; ABO bulb emission is zeroed, the emitter mask and the
light budget stay what they were.
"""
from __future__ import annotations

import re

import bpy
from mathutils import Vector

import abo_assets as abo
import furnish_rooms as fr
import room_dressing as rd

HEADROOM_M = 2.05
OVER_TABLE_M = 0.7


def _kind(e) -> str | None:
    k = (e.get("keywords") or [""])[0]
    n = e["name"].lower()
    w, h, d = e["extent_m"]
    if abs(w - d) / max(w, d) > 0.25 or "sconce" in k or re.search("sconce|壁灯|벽|wall", n):
        return None                                         # wall-mounted or not round: not for a ceiling
    if "chandelier" in k or (re.search("chandelier|샹들리에|枝形|吊灯", n) and w > 0.45):
        return "chandelier"
    if "close-to-ceiling" in k or re.search("flush|嵌入|플러시|마운트", n):
        return "flush"
    if "pendant" in k or re.search("pendant|吊坠|펜던트", n):
        return "pendant"
    return None


_POOLS = {}


def pool(kind):
    if not _POOLS:
        for e in abo.entries():
            if e["product_type"] in ("LIGHT_FIXTURE", "HOME_LIGHTING_AND_LAMPS") and e["triangles"] <= abo.MAX_TRIANGLES:
                if (k := _kind(e)) is not None:
                    _POOLS.setdefault(k, []).append(e)
    return _POOLS.get(kind, [])


def _no_emission(o):
    for slot in o.material_slots:
        nt = slot.material.node_tree if slot.material and slot.material.use_nodes else None
        for n in (nt.nodes if nt else ()):
            if n.type == "BSDF_PRINCIPLED" and "Emission Strength" in n.inputs:
                n.inputs["Emission Strength"].default_value = 0.0
            elif n.type == "EMISSION":
                n.inputs["Strength"].default_value = 0.0


def _room_at(rooms, x, y):
    for name, r in rooms.items():
        if r.box[0] <= x <= r.box[1] and r.box[2] <= y <= r.box[3] and r.on_floor(x, y):
            return name, r
    return None, None


def dress(rng, stats):
    stats.setdefault("ceiling_fixtures", {})
    scene, deps = bpy.context.scene, bpy.context.evaluated_depsgraph_get()
    rooms = {n: fr.Room(n, p, scene, deps) for n, p in rd._rooms().items() if "floor" in p}
    tops = rd._tops()
    pucks = [o for o in tops if rd._factory(o.name) == "CeilingLightFactory"]
    tables = [o for o in tops if rd._factory(o.name) in ("TableDiningFactory", "KitchenIslandFactory", "StoneDiningTableFactory")]
    chosen, hung_over = {}, set()                           # room -> (kind, entry); tables that already have a fixture
    by_room = {}
    for p in pucks:
        t = p.matrix_world.translation
        name, room = _room_at(rooms, t.x, t.y)
        if room is not None:
            by_room.setdefault(name, []).append(p)
    for name, ps in sorted(by_room.items()):
        room = rooms[name]
        here = [t for t in tables if (f := fr.footprint(t)) and room.on_floor((f[0] + f[1]) / 2, (f[2] + f[3]) / 2)]
        if room.type == "dining-room":
            want = "chandelier" if rng.random() < 0.4 else "pendant"
        elif room.type == "living-room":
            want = "chandelier" if rng.random() < 0.4 else "flush"
        elif room.type == "kitchen" and here:
            want = "pendant"
        else:
            want = "flush"
        for i, p in enumerate(sorted(ps, key=lambda p: min(((p.matrix_world.translation - _centre(t)).length for t in here), default=0))):
            ceiling = fr.footprint(p)[5]
            at = p.matrix_world.translation.copy()
            kind, floor_limit = "flush", room.z + HEADROOM_M
            if want != "flush" and i == 0 and here and here[0].name not in hung_over:
                tf = fr.footprint(here[0])
                at = _centre(here[0]); kind = want; floor_limit = tf[5] + OVER_TABLE_M; hung_over.add(here[0].name)
            elif want == "chandelier" and room.type == "living-room" and i == 0:
                kind = "chandelier"
            o = _fixture(chosen, name, kind, ceiling, floor_limit, rng, stats) or _fixture(chosen, name, "flush", ceiling, room.z + HEADROOM_M, rng, stats)
            if o is None:
                continue
            f = fr.footprint(o)
            o.location += Vector((at.x - (f[0] + f[1]) / 2, at.y - (f[2] + f[3]) / 2, ceiling - 0.005 - f[5]))
            bpy.context.view_layer.update()
            bottom = fr.footprint(o)[4]
            for light in [c for c in p.children_recursive if c.type == "LIGHT"]:
                m = light.matrix_world.copy()
                light.parent = None
                light.matrix_world = m
                light.location = (at.x, at.y, bottom - 0.02)
                light.data.shadow_soft_size = max(light.data.shadow_soft_size, 0.05)
            for c in list(p.children_recursive):
                if c.type != "LIGHT":
                    bpy.data.objects.remove(c, do_unlink=True)
            bpy.data.objects.remove(p, do_unlink=True)
            stats["ceiling_fixtures"][kind] = stats["ceiling_fixtures"].get(kind, 0) + 1
    _add_missing(rooms, by_room, rd._tops(), chosen, rng, stats)        # fresh: the pucks above are gone
    _over_service(rooms, chosen, rng, stats)
    bpy.context.view_layer.update()


DEFAULT_W = 92.5          # Infinigen's ceiling PointLamp in the v2a scenes
M2_PER_FIXTURE = 15.0
CEILING_LAMPS = ("CeilingLightFactory", "CeilingClassicLampFactory")


def _add_missing(rooms, by_room, tops, chosen, rng, stats):
    """Rooms the solver left without a ceiling light (solve_medium off places none: 35718226 had 0 of v2a's ~16) get fixtures:
    one per M2_PER_FIXTURE of floor, on a grid over the floor at least 0.6 m from its edge, each with a point light like
    Infinigen's (copied from a lamp in the scene when there is one, so the adapter treats it the same)."""
    template = next((o.data for o in bpy.data.objects if o.type == "LIGHT" and o.data.type == "POINT"
                     and o.name.startswith("PointLampFactory")), None)
    lit = set(by_room)
    for o in bpy.data.objects:                                   # track spots / pendants already hung count as the room's light
        if o.type == "LIGHT":
            name, room = _room_at(rooms, o.location.x, o.location.y)
            if room is not None and o.location.z > room.z + 2.0:
                lit.add(name)
    for t in tops:
        if rd._factory(t.name) in CEILING_LAMPS:
            c = t.matrix_world.translation
            name, _ = _room_at(rooms, c.x, c.y)
            lit.add(name)
    for name, room in sorted(rooms.items()):
        if name in lit or room.type in ("balcony", "staircase-room"):
            continue
        x0, x1, y0, y1 = room.box
        pts = [(x, y) for x in _steps(x0 + 0.6, x1 - 0.6) for y in _steps(y0 + 0.6, y1 - 0.6)
               if all(room.on_floor(x + dx, y + dy) for dx, dy in ((0, 0), (0.6, 0), (-0.6, 0), (0, 0.6), (0, -0.6)))]
        if not pts:
            continue
        area = len(pts) * 0.25                               # 0.5 m grid cells
        from room_planner import proc_assets
        n = max(1, round(area / (6.0 if proc_assets.VENUE in ("grocery", "convenience", "pharmacy", "clinic-reception", "exam-room", "dental-room", "physio-room", "boutique") else M2_PER_FIXTURE)))   # a sales floor is bright and even
        picks = _spread(pts, n)
        # The wall mesh's top is the ceiling. A ray up from the floor hit a desk first in a furnished office (ceiling read as 0.75 m,
        # no fixture fit, the open office stayed dark; 2026-10-16).
        if room.wall is not None:
            ceiling = max((room.wall.matrix_world @ Vector(c)).z for c in room.wall.bound_box)
        else:
            hit = bpy.context.scene.ray_cast(bpy.context.evaluated_depsgraph_get(), Vector((*picks[0], room.z + 2.2)),
                                             Vector((0, 0, 1)), distance=6.0)
            ceiling = hit[1].z if hit[0] else room.z + 2.8
        kind = "pendant" if room.type in ("warehouse", "garage", "factory-office") else "flush"
        for x, y in picks:
            o = _fixture(chosen, name, kind, ceiling, room.z + HEADROOM_M, rng, stats) or \
                _fixture(chosen, name, "flush", ceiling, room.z + HEADROOM_M, rng, stats)
            if o is None:
                break
            f = fr.footprint(o)
            o.location += Vector((x - (f[0] + f[1]) / 2, y - (f[2] + f[3]) / 2, ceiling - 0.005 - f[5]))
            bpy.context.view_layer.update()
            data = template.copy() if template is not None else bpy.data.lights.new("ir_ceiling_point", "POINT")
            if template is None:
                data.energy = DEFAULT_W
            light = bpy.data.objects.new(f"PointLampFactory(added).spawn_asset({stats['ceiling_fixtures'].get('added', 0)})", data)
            bpy.context.scene.collection.objects.link(light)
            light.location = (x, y, fr.footprint(o)[4] - 0.02)
            light.data.shadow_soft_size = max(light.data.shadow_soft_size, 0.05)
            stats["ceiling_fixtures"]["added"] = stats["ceiling_fixtures"].get("added", 0) + 1


SERVICE = {"CafeCounterFactory": (3, 0.9), "CafeTableFactory": (1, 0.75)}     # pendants per object, height above its top
PENDANT_W = 60.0                                                 # counter/table pendants: warm work light, above the track accents


def _over_service(rooms, chosen, rng, stats):
    """Pendants over every cafe counter (3 along it) and table (1): the light a cafe is recognised by. Each gets a soft point light."""
    template = next((o.data for o in bpy.data.objects if o.type == "LIGHT" and o.data.type == "POINT"
                     and o.name.startswith("PointLampFactory")), None)
    hung = []
    for t in rd._tops():
        spec = SERVICE.get(rd._factory(t.name))
        if spec is None:
            continue
        n, above = spec
        if rd._factory(t.name) == "CafeTableFactory" and len(hung) >= 7:   # a few pendants, not one per table (café M: '~15 cone pendants
            continue                                                        # with blown undersides' over a 12-table room)
        f = fr.footprint(t)
        name, room = _room_at(rooms, (f[0] + f[1]) / 2, (f[2] + f[3]) / 2)
        if room is None or room.wall is None:
            continue
        fb = room.box
        if ((fb[1] - fb[0]) * (fb[3] - fb[2]) < 20.0 or name.startswith(("office", "meeting"))) and rd._factory(t.name) == "CafeTableFactory":
            continue                                             # no café pendant over a small staff room's round table: it hung at head
            # height and 'filled a third of every frame' (floor G r33, 3 of 3)
        ceiling = max((room.wall.matrix_world @ Vector(c)).z for c in room.wall.bound_box)
        long_x = (f[1] - f[0]) >= (f[3] - f[2])
        for k in range(n):
            u = (k + 0.5) / n
            x = f[0] + u * (f[1] - f[0]) if long_x else (f[0] + f[1]) / 2
            y = (f[2] + f[3]) / 2 if long_x else f[2] + u * (f[3] - f[2])
            if any((x - hx) ** 2 + (y - hy) ** 2 < 0.36 for hx, hy in hung):
                continue
            from room_planner import proc_assets
            kind = proc_assets.STYLE.get("fixture", "pendant") if rd._factory(t.name) == "CafeCounterFactory" else "pendant"
            shade = proc_assets.STYLE.get("pendant_shade")
            if shade:                                            # the reference's pendant (style evals: random ABO domes, copper x15)
                drop = max(0.5, min(1.2, ceiling - (f[5] + above) - 0.25))
                o = proc_assets.DomePendantFactory(0, shade, drop).spawn_asset(len(hung))
            else:
                o = _fixture(chosen, name + ":service", kind, ceiling, f[5] + above, rng, stats) or \
                    _fixture(chosen, name + ":service", "pendant", ceiling, f[5] + above, rng, stats)
            if o is None:
                break
            ff = fr.footprint(o)
            o.location += Vector((x - (ff[0] + ff[1]) / 2, y - (ff[2] + ff[3]) / 2, ceiling - 0.005 - ff[5]))
            bpy.context.view_layer.update()
            data = template.copy() if template is not None else bpy.data.lights.new("ir_pendant_point", "POINT")
            data.energy = PENDANT_W
            light = bpy.data.objects.new(f"PointLampFactory(pendant).spawn_asset({len(hung)})", data)
            bpy.context.scene.collection.objects.link(light)
            light.location = (x, y, fr.footprint(o)[4] - 0.02)
            light.data.shadow_soft_size = max(light.data.shadow_soft_size, 0.05)
            hung.append((x, y))
            stats["ceiling_fixtures"]["pendant_service"] = stats["ceiling_fixtures"].get("pendant_service", 0) + 1


def _steps(a, b, step=0.5):
    out, v = [], a
    while v <= b:
        out.append(v); v += step
    return out


def _spread(pts, n):
    """n points far apart (farthest-point sampling from the one nearest the centroid)."""
    cx, cy = sum(p[0] for p in pts) / len(pts), sum(p[1] for p in pts) / len(pts)
    picks = [min(pts, key=lambda p: (p[0] - cx) ** 2 + (p[1] - cy) ** 2)]
    while len(picks) < n:
        picks.append(max(pts, key=lambda p: min((p[0] - q[0]) ** 2 + (p[1] - q[1]) ** 2 for q in picks)))
    return picks


def _centre(o):
    f = fr.footprint(o)
    return Vector(((f[0] + f[1]) / 2, (f[2] + f[3]) / 2, 0))


def _fixture(chosen, room, kind, ceiling, floor_limit, rng, stats):
    """The room's model of this kind (picked once), hanging no lower than floor_limit; None when nothing of the kind fits."""
    from room_planner import proc_assets as _pa
    if _pa.STYLE.get("living_pendant") == "drum" and room.startswith(("living", "dining")) and kind != "flush":      # kit: a big fabric DRUM pendant over the sofa / table (P2b refs)
        from room_planner import proc_home as _ph1
        o = _ph1.DrumPendantFactory(0, max(0.5, min(1.0, ceiling - floor_limit - 0.2))).spawn_asset(sum(stats["ceiling_fixtures"].values()))
        bpy.context.view_layer.update()
        return o
    if any(room.startswith(p_) for p_ in (_pa.STYLE.get("recessed_rooms") or ())):          # kit recessed_rooms=[name prefixes]: recessed downlights everywhere listed (apartment bedrooms / hall / closets)
        from room_planner import proc_home as _ph2
        o = _ph2.RecessedSpotFactory(0).spawn_asset(sum(stats["ceiling_fixtures"].values()))
        bpy.context.view_layer.update()
        return o
    if (_pa.STYLE.get("service_light") == "recessed" and room.startswith(("kitchen", "utility", "restroom", "bathroom"))) or \
            (_pa.STYLE.get("hall_light") == "recessed" and room.startswith("hallway")):      # kit hall_light=recessed: corridor downlights (O2 hallway ref)      # kit: recessed downlights in the service rooms (G/H kitchen ref), not a faceted ABO pendant
        from room_planner import proc_home as _ph0
        o = _ph0.RecessedSpotFactory(0).spawn_asset(sum(stats["ceiling_fixtures"].values()))
        bpy.context.view_layer.update()
        return o
    if kind == "pendant" and room.startswith("dining") and _pa.STYLE.get("dining_pendant") == "linear":      # kit: a long linear pendant over the dining table (P2b r6 refs)
        from room_planner import proc_home as _ph
        o = _ph.LinearPendantFactory(0, max(0.5, ceiling - floor_limit - 0.05)).spawn_asset(sum(stats["ceiling_fixtures"].values()))
        bpy.context.view_layer.update()
        return o
    key = (room, kind)
    if key not in chosen:
        fits = [e for e in pool(kind) if ceiling - e["extent_m"][1] >= floor_limit]
        if not fits:
            return None
        chosen[key] = rng.choice(fits)
    e = chosen[key]
    o = abo._import(e, f"AboCeilingFixtureFactory({e['id']}).spawn_asset({sum(stats['ceiling_fixtures'].values())})")
    _no_emission(o)
    bpy.context.view_layer.update()
    return o
