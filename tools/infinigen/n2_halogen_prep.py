"""Halogen strip lamps for the N2 dark-lighting variants (IR_PIPELINE 10-27: only old yellow halogen lamps glow in a gloomy building).

    blender -b IN.lit.blend -P n2_halogen_prep.py -- IN.lit.blend OUT.blend

Removes every native non-SUN lamp and puts ir_halogen_strip_* area lights (rectangle 1.2 x 0.1 m, energy 100 = watt scale 1, so a
recipe's watts is the strip's power) along each room's long axis under the ceiling, every ~2.6 m, plus a thin emissive bar
(material ir_bulb_halogen: the colorlight bridge scales it with the lit fixtures). Camera-visible bars, hidden-from-camera lights.
"""
import bpy, sys
from mathutils import Vector

src, dst = sys.argv[sys.argv.index("--") + 1:][:2]
bpy.ops.wm.open_mainfile(filepath=src)
sc = bpy.context.scene
for o in [o for o in bpy.data.objects if o.type == "LIGHT" and o.data.type != "SUN"]:
    bpy.data.objects.remove(o, do_unlink=True)
m = bpy.data.materials.new("ir_bulb_halogen"); m.use_nodes = True
b = m.node_tree.nodes["Principled BSDF"]; b.inputs["Base Color"].default_value = (0.02, 0.02, 0.02, 1)
b.inputs["Emission Color"].default_value = (1.0, 0.62, 0.25, 1); b.inputs["Emission Strength"].default_value = 6.0
n = 0
for fl in [o for o in bpy.data.objects if o.type == "MESH" and o.name.endswith(".floor")]:
    cs = [fl.matrix_world @ Vector(c) for c in fl.bound_box]
    x0, x1 = min(c.x for c in cs), max(c.x for c in cs); y0, y1 = min(c.y for c in cs), max(c.y for c in cs)
    long_x = (x1 - x0) >= (y1 - y0); L = (x1 - x0) if long_x else (y1 - y0)
    LEN = min(3.0, max(1.2, L - 1.2)); cnt = max(1, round((L - 0.6) / (LEN + 1.6))); zc = 3.07 - 0.05
    for i in range(cnt):
        t = (i + 0.5) / cnt; px = x0 + (x1 - x0) * t if long_x else (x0 + x1) / 2; py = (y0 + y1) / 2 if long_x else y0 + (y1 - y0) * t
        ld = bpy.data.lights.new(f"ir_halogen_strip_{n}", "AREA"); ld.shape = "RECTANGLE"; ld.size, ld.size_y = (LEN, 0.08) if long_x else (0.08, LEN)
        ld.energy = 100.0; ld.color = (1.0, 0.62, 0.25); ld.spread = 3.14159 * 0.4
        lo = bpy.data.objects.new(f"ir_halogen_strip_{n}", ld); lo.location = (px, py, zc); lo.visible_camera = False; sc.collection.objects.link(lo)
        bpy.ops.mesh.primitive_cube_add(size=1.0, location=(px, py, zc + 0.02)); bar = bpy.context.object; bar.name = f"ir_halogen_bar_{n}"
        bar.scale = (LEN, 0.08, 0.03) if long_x else (0.08, LEN, 0.03); bar.data.materials.append(m); bar.visible_shadow = False; n += 1
# bare old-halogen spot bulbs between the strips: small radius, 70 deg cone -> hard, many shadows (user 10-27: dark ambient + indoor lamps casting shadows)
k = 0
for fl in [o for o in bpy.data.objects if o.type == "MESH" and o.name.endswith(".floor")]:
    cs = [fl.matrix_world @ Vector(c) for c in fl.bound_box]
    x0, x1 = min(c.x for c in cs), max(c.x for c in cs); y0, y1 = min(c.y for c in cs), max(c.y for c in cs)
    long_x = (x1 - x0) >= (y1 - y0); L = (x1 - x0) if long_x else (y1 - y0); cnt = max(1, round((L - 0.6) / 2.2))
    for i in range(cnt):
        t = (i + 0.5) / cnt; side = 0.3 if i % 2 else -0.3
        px = x0 + (x1 - x0) * t if long_x else (x0 + x1) / 2 + side; py = (y0 + y1) / 2 + side if long_x else y0 + (y1 - y0) * t
        ld = bpy.data.lights.new(f"ir_halogen_strip_spot{k}", "SPOT"); ld.spot_size = 1.25; ld.spot_blend = 0.25; ld.shadow_soft_size = 0.02
        ld.energy = 40.0; ld.color = (1.0, 0.62, 0.25)
        lo = bpy.data.objects.new(f"ir_halogen_strip_spot{k}", ld); lo.location = (px, py, 3.0); lo.visible_camera = False; sc.collection.objects.link(lo); k += 1
# low caged halogen lamps (user 10-27: low lamps too -> long grazing reflections on the glossy floor): hallway and utility rooms, 0.45 m up, near the walls, aimed along the room
q = 0
for fl in [o for o in bpy.data.objects if o.type == "MESH" and o.name.endswith(".floor") and o.name.split("_")[0] in ("hallway", "utility")]:
    cs = [fl.matrix_world @ Vector(c) for c in fl.bound_box]
    x0, x1 = min(c.x for c in cs), max(c.x for c in cs); y0, y1 = min(c.y for c in cs), max(c.y for c in cs)
    long_x = (x1 - x0) >= (y1 - y0); L = (x1 - x0) if long_x else (y1 - y0); cnt = max(1, round(L / 5.0))
    for i in range(cnt):
        t = (i + 0.5) / cnt; sgn = 1 if i % 2 else -1
        if long_x: px, py, d = x0 + (x1 - x0) * t, (y0 + y1) / 2 + sgn * ((y1 - y0) / 2 - 0.3), Vector((-sgn, 0, 0.05))
        else: px, py, d = (x0 + x1) / 2 + sgn * ((x1 - x0) / 2 - 0.3), y0 + (y1 - y0) * t, Vector((0, -sgn, 0.05))
        ld = bpy.data.lights.new(f"ir_halogen_strip_low{q}", "SPOT"); ld.spot_size = 1.1; ld.spot_blend = 0.3; ld.shadow_soft_size = 0.03
        ld.energy = 25.0; ld.color = (1.0, 0.62, 0.25)
        lo = bpy.data.objects.new(f"ir_halogen_strip_low{q}", ld); lo.location = (px, py, 0.45); lo.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
        lo.visible_camera = False; sc.collection.objects.link(lo)
        bpy.ops.mesh.primitive_uv_sphere_add(radius=0.05, location=(px, py, 0.45)); bulb = bpy.context.object; bulb.name = f"ir_halogen_bar_low{q}"; bulb.data.materials.append(m); bulb.visible_shadow = False; q += 1
print("HALOGEN strips", n, "spots", k, "low", q)
bpy.ops.wm.save_as_mainfile(filepath=dst)
