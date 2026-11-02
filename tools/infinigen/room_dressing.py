"""Room-level dressing for the activity pass (user 2026-10-14, looking at v2a frames):

  * appliances  -- Infinigen's mini fridge is a big rough metal box with a coloured plastic top; real ones are stainless, white or
                   black. Fridge/dishwasher/microwave/oven bodies get one of those finishes (glass, emitters left alone).
  * floor plants -- a potted plant standing alone in a corner reads as dropped there: one with no furniture within 0.7 m goes.
  * wall decor   -- blank walls: living/dining/bedroom/hallway get framed art (WallArtFactory; tidy.hang_art paints it with a CC0
                   work) on a clear stretch of wall at eye height, and a bathroom sink without a mirror gets one above it.

Walls are found by ray casts from the room's own floor at picture height; a spot is used only when the whole frame rectangle hits
that room's wall at one depth (no window, door, shelf or corner in it) and nothing stands within 0.45 m in front of it.
"""
from __future__ import annotations

import math
import re

import bpy
from mathutils import Vector

ROOM_PART = re.compile(r"^(?P<room>[a-z-]+_\d+/\d+)\.(?P<part>wall|floor)$")
APPLIANCES = ("BeverageFridgeFactory", "DishwasherFactory", "MicrowaveFactory", "OvenFactory")
PLANTS = ("LargePlantContainerFactory", "PlantContainerFactory")
ART_ROOMS = {"living-room": 2, "dining-room": 1, "bedroom": 2, "hallway": 1}
SINKS = ("StandingSinkFactory", "BathroomSinkFactory")
GLASSY = {"BSDF_GLASS", "BSDF_REFRACTION", "BSDF_TRANSPARENT", "EMISSION"}
#: rugs as sold (sRGB): Infinigen's rugs take any hue at saturation up to 0.4 or an art print, and read as a game asset
RUGS = ["c9bba3", "a89f91", "6e6a64", "3f3d3b", "d8d0c0", "4a5468", "8a5a44", "6d6a4f", "b7a58a", "5b4a42"]


def _factory(name):
    return name.split("(")[0]


def _tops():
    return [o for o in bpy.data.objects if ".spawn_asset(" in o.name and not (o.parent and ".spawn_asset(" in o.parent.name)]


def _nodes(tree, seen=None):
    seen = set() if seen is None else seen
    if tree is None or tree.as_pointer() in seen:
        return
    seen.add(tree.as_pointer())
    for n in tree.nodes:
        yield n
        if n.type == "GROUP":
            yield from _nodes(n.node_tree, seen)


def _finish(name, rgb, metallic, rough):
    m = bpy.data.materials.get(name)
    if m is None:
        m = bpy.data.materials.new(name); m.use_nodes = True
        b = m.node_tree.nodes["Principled BSDF"]
        b.inputs["Base Color"].default_value = (*rgb, 1.0)
        b.inputs["Metallic"].default_value = metallic; b.inputs["Roughness"].default_value = rough
    return m


def neutral_appliances(rng, stats):
    finishes = {"stainless": _finish("ir_appliance_stainless", (0.62, 0.62, 0.61), 1.0, 0.28),
                "white": _finish("ir_appliance_white", (0.80, 0.80, 0.78), 0.0, 0.35),
                "black": _finish("ir_appliance_black", (0.012, 0.012, 0.014), 0.0, 0.3)}
    trim = _finish("ir_appliance_trim", (0.02, 0.02, 0.02), 0.0, 0.5)
    for o in _tops():
        if _factory(o.name) not in APPLIANCES:
            continue
        body = finishes[rng.choice(("stainless", "stainless", "white", "black"))]
        for ob in [o, *o.children_recursive]:
            for slot in getattr(ob, "material_slots", []):
                m = slot.material
                if m is None or not m.use_nodes or any(n.type in GLASSY for n in _nodes(m.node_tree)):
                    continue
                pr = [n for n in _nodes(m.node_tree) if n.type == "BSDF_PRINCIPLED"]
                if any((n.inputs.get("Transmission Weight") and n.inputs["Transmission Weight"].default_value > 0.05)
                       or n.inputs["Emission Strength"].default_value > 0 for n in pr):
                    continue
                metal = any(n.inputs["Metallic"].is_linked or n.inputs["Metallic"].default_value > 0.5 for n in pr)
                slot.material = body if metal or body is not finishes["stainless"] else trim
                stats["appliance_slots"] += 1


def _xy_gap(a, b):
    """Horizontal gap between the world bounding boxes of a and b (0 when they overlap)."""
    def box(o):
        pts = [o.matrix_world @ Vector(c) for x in [o, *o.children_recursive] if x.type == "MESH" for c in x.bound_box] or \
              [o.matrix_world.translation]
        return min(p.x for p in pts), max(p.x for p in pts), min(p.y for p in pts), max(p.y for p in pts)
    ax0, ax1, ay0, ay1 = box(a); bx0, bx1, by0, by1 = box(b)
    return math.hypot(max(0.0, max(ax0, bx0) - min(ax1, bx1)), max(0.0, max(ay0, by0) - min(ay1, by1)))


def drop_lonely_floor_plants(stats, near_m=0.7):
    tops = _tops()
    not_furniture = ("Door", "Window", "WallArt", "Mirror", "Pillar")   # a glass door beside a lone plant kept it (17469963)
    furniture = [o for o in tops if _factory(o.name) not in PLANTS and max(o.dimensions) > 0.4
                 and not any(k in _factory(o.name) for k in not_furniture)]
    for p in [o for o in tops if _factory(o.name) in PLANTS]:
        zmin = min((p.matrix_world @ Vector(c)).z for c in p.bound_box)
        if zmin > 0.25:                                   # on furniture: the activity pass placed it with a reason
            continue
        if not any(_xy_gap(p, f) < near_m for f in furniture):
            for c in list(p.children_recursive) + [p]:
                bpy.data.objects.remove(c, do_unlink=True)
            stats["lonely_plants_removed"] += 1


def _rooms():
    out = {}
    for o in bpy.data.objects:
        m = ROOM_PART.match(o.name)
        if m and o.type == "MESH":
            out.setdefault(m.group("room"), {})[m.group("part")] = o
    return out


def _clear_rect(scene, deps, wall, p, n, w, h, depth=0.3):
    """The w x h rectangle centred on p, facing n, lies flat on `wall` with nothing in front of it."""
    up = Vector((0, 0, 1)); side = n.cross(up).normalized()
    for i in (-0.5, -0.25, 0, 0.25, 0.5):
        for j in (-0.5, 0, 0.5):
            q = p + side * (i * w) + up * (j * h)
            hit = scene.ray_cast(deps, q + n * depth, -n, distance=depth + 0.08)
            if not hit[0] or hit[4] != wall or abs((hit[1] - q).length) > 0.04:
                return False
    for i in (-0.4, 0, 0.4):                             # 0.45 m of free air in front (a shelf or wardrobe there: no)
        q = p + side * (i * w) + n * 0.03
        if scene.ray_cast(deps, q, n, distance=0.45)[0]:
            return False
    return True


def _wall_spots(scene, deps, room, rng, eye_z):
    """Candidate (point, inward normal) on the room's wall, found by casting from points standing on the room's own floor."""
    floor, wall = room["floor"], room["wall"]
    bb = [floor.matrix_world @ Vector(c) for c in floor.bound_box]
    x0, x1 = min(p.x for p in bb), max(p.x for p in bb); y0, y1 = min(p.y for p in bb), max(p.y for p in bb)
    spots = []
    for _ in range(40):
        o = Vector((rng.uniform(x0, x1), rng.uniform(y0, y1), eye_z))
        down = scene.ray_cast(deps, o, Vector((0, 0, -1)), distance=3.0)
        if not down[0] or down[4] != floor:
            continue
        a = rng.uniform(0, 2 * math.pi)
        d = Vector((math.cos(a), math.sin(a), 0))
        hit = scene.ray_cast(deps, o, d, distance=12.0)
        if hit[0] and hit[4] == wall and abs(hit[2].z) < 0.05 and hit[2].dot(d) < -0.5:
            spots.append((hit[1], Vector((hit[2].x, hit[2].y, 0)).normalized()))
    return spots


def hang_wall_decor(rng, stats, spawn, wall_art_factory, mirror_factory):
    scene, deps = bpy.context.scene, bpy.context.evaluated_depsgraph_get()
    rooms = _rooms()
    floors = {r["floor"]: name for name, r in rooms.items() if "floor" in r}

    def room_of(p, front):
        """The room whose floor lies under a point just in front of the decor (floor bounding boxes overlap in L-shaped
        flats: counting by box put a dining-room picture in the living room, which then got none)."""
        hit = scene.ray_cast(deps, p + front * 0.3, Vector((0, 0, -1)), distance=4.0)
        return floors.get(hit[4]) if hit[0] else None

    decor = []                                                  # (point, room)
    for o in _tops():
        if _factory(o.name) in ("WallArtFactory", "MirrorFactory"):
            front = (o.matrix_world.to_3x3() @ Vector((1, 0, 0))).normalized()
            decor.append((o.matrix_world.translation.copy(), room_of(o.matrix_world.translation, front)))
    for name, room in sorted(rooms.items()):
        rtype = name.split("_")[0]
        if rtype not in ART_ROOMS or "floor" not in room or "wall" not in room:
            continue
        floor_z = max((room["floor"].matrix_world @ Vector(c)).z for c in room["floor"].bound_box)
        have = sum(1 for _, r in decor if r == name)
        want = ART_ROOMS[rtype] - have
        for p, n in _wall_spots(scene, deps, room, rng, floor_z + 1.5):
            if want <= 0:
                break
            w, h = rng.uniform(0.5, 1.1), rng.uniform(0.4, 0.8)
            if any((p - d).length < 1.4 for d, _ in decor) or not _clear_rect(scene, deps, room["wall"], p, n, w + 0.1, h + 0.1):
                continue
            o = spawn(wall_art_factory, width=w, height=h)
            if o is None:
                continue
            o.rotation_euler = (0, 0, math.atan2(n.y, n.x))     # WallArt faces local +x, its back at -x
            o.location = p + n * 0.012
            decor.append((p.copy(), name)); want -= 1
            stats["wall_art_added"] += 1
            bpy.context.view_layer.update()
    # a bathroom sink without a mirror above it
    for s in [o for o in _tops() if _factory(o.name) in SINKS]:
        top = max((s.matrix_world @ Vector(c)).z for c in s.bound_box)
        c = s.matrix_world.translation
        if any(math.hypot(d.x - c.x, d.y - c.y) < 1.2 and d.z > top for d, _ in decor):
            continue
        back = -(s.matrix_world.to_3x3() @ Vector((1, 0, 0))).normalized()       # Infinigen front is +x
        o0 = Vector((c.x, c.y, top + 0.55))
        hit = scene.ray_cast(deps, o0, back, distance=1.2)
        if not hit[0] or abs(hit[2].z) > 0.05:
            continue
        n = Vector((hit[2].x, hit[2].y, 0)).normalized()
        w = min(0.7, max(0.4, s.dimensions[1] * 0.9)); h = 0.7
        p = hit[1] + Vector((0, 0, 0.05))
        if not _clear_rect(scene, deps, hit[4], p, n, w, h):
            continue
        o = spawn(mirror_factory, width=w, height=h)
        if o is None:
            continue
        o.rotation_euler = (0, 0, math.atan2(n.y, n.x)); o.location = p + n * 0.012
        decor.append((p.copy(), None)); stats["mirrors_added"] += 1
        bpy.context.view_layer.update()


def _in_room_xy(floor, p):
    bb = [floor.matrix_world @ Vector(c) for c in floor.bound_box]
    return min(q.x for q in bb) <= p.x <= max(q.x for q in bb) and min(q.y for q in bb) <= p.y <= max(q.y for q in bb)


def _srgb_lin(hx):
    c = [int(hx[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    return tuple(x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c)


def mute_rugs(rng, stats):
    """Each rug gets a plain muted wool: palette colour with a fine fibre noise towards a darker tone."""
    for o in _tops():
        if _factory(o.name) != "RugFactory":
            continue
        base = _srgb_lin(rng.choice(RUGS))
        m = bpy.data.materials.new(f"ir_rug_{stats['rugs_muted']}"); m.use_nodes = True
        nt = m.node_tree; b = nt.nodes["Principled BSDF"]
        noise = nt.nodes.new("ShaderNodeTexNoise"); noise.inputs["Scale"].default_value = rng.uniform(25, 60)
        mix = nt.nodes.new("ShaderNodeMixRGB"); mix.inputs["Fac"].default_value = 1.0
        mix.inputs["Color1"].default_value = (*base, 1); mix.inputs["Color2"].default_value = (*[c * 0.7 for c in base], 1)
        nt.links.new(noise.outputs["Fac"], mix.inputs["Fac"]); nt.links.new(mix.outputs["Color"], b.inputs["Base Color"])
        b.inputs["Roughness"].default_value = 0.92
        for ob in [o, *o.children_recursive]:
            for slot in getattr(ob, "material_slots", []):
                slot.material = m
        stats["rugs_muted"] += 1


def close_exterior_doors(stats):
    """Doors that lead outside are shut (user 2026-10-16); doors between rooms keep Infinigen's random swing. A door is exterior when
    a point 0.7 m out on one side of its wall is over no room floor. Infinigen hangs each leaf on its placeholder with the swing as
    rotation z about the hinge, so closing it is rotation z = 0."""
    import furnish_rooms as fr
    scene, deps = bpy.context.scene, bpy.context.evaluated_depsgraph_get()
    rooms = [fr.Room(n, p, scene, deps) for n, p in _rooms().items() if "floor" in p]
    on_floor = lambda x, y: any(r.on_floor(x, y) for r in rooms)  # noqa: E731
    closed = 0
    for o in bpy.data.objects:
        f = _factory(o.name)
        if "Door" not in f or "Casing" in f or o.parent is None:
            continue
        c = o.parent.matrix_world.translation.copy()             # the opening's centre in the wall (an open leaf swings ~0.45 m out)
        n = (o.parent.matrix_world.to_3x3() @ Vector((0, 1, 0))); n.z = 0
        if n.length < 1e-6:
            continue
        n.normalize()
        a, b = c + n * 0.7, c - n * 0.7
        if not (on_floor(a.x, a.y) and on_floor(b.x, b.y)):
            # rotation z = 0 is not always shut: some leaves carry the swing in their mesh (office r2 2026-10-16: 'closed' leaves
            # rendered half open). Search the z rotation that lays the leaf flat in the opening: thinnest across the wall normal,
            # centred on the opening.
            # Area-weighted face centres: the panel dominates the area, so the closed pose has the smallest spread across the wall
            # normal. Vertex percentiles (the previous measure) were swayed by dense handle/hinge meshes and shut a LiteDoor at -30
            # deg, 60 deg open (clinic r5, 2026-10-16); the along term picks the one of the two flat poses that sits in the opening.
            fs = [(p.center.copy(), p.area) for p in o.data.polygons] if o.type == "MESH" else []
            fs = fs or [(Vector(q), 1.0) for q in o.bound_box]
            A = sum(a for _, a in fs) or 1.0
            t = Vector((-n.y, n.x, 0))
            def cost(rz):
                o.rotation_euler[2] = rz
                bpy.context.view_layer.update()
                M = o.matrix_world
                w = [((M @ q - c).dot(n), (M @ q - c).dot(t), a) for q, a in fs]
                mn = sum(x * a for x, _, a in w) / A
                sd = (sum(a * (x - mn) ** 2 for x, _, a in w) / A) ** 0.5
                return sd + 0.1 * abs(sum(y * a for _, y, a in w) / A)
            o.rotation_mode = "XYZ"
            o.rotation_euler[2] = min((math.radians(d) for d in range(-180, 180, 2)), key=cost)
            closed += 1
    bpy.context.view_layer.update()
    stats["exterior_doors_closed"] = closed
