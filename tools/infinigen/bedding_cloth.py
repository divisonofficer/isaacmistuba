"""Ray-supported runner cloth, metres, with rounded shoulders and scalloped hems.

The callback takes (across, along) and returns a world-space surface Vector
or None outside the bed. It must expose half_span (actual supported mattress
or duvet half-width, never the whole bed/headboard bounding box) and
point(across, along, z_offset), mapping bed coordinates into world space.
width is the strip dimension along the bed; length is its total cross-bed
arc length; hang is the vertical drop at each end. All top columns are raycast.
"""
import math
import bpy
from mathutils import Vector


def drape_strip(bed_top_surface_ray, width, length, hang):
    """Return a 2 mm thick mesh supported within 7 mm of the ray surface."""
    if not (width > 0 and length > 0 and 0 < hang < length / 2):
        raise ValueError('Positive dimensions and hang < length/2 required')
    ray = bed_top_surface_ray
    half = float(ray.half_span)
    if length < 2 * half + 2 * hang:
        raise ValueError('length must span the bed plus both hanging ends')
    shoulder = 0.045
    travel = half - shoulder + math.pi * shoulder / 2 + hang - shoulder
    ease = min(.006, max(0, length - 2 * half - 2 * hang) / 12)
    nu, nv = 160, 36
    verts, faces, supported = [], [], []
    for i in range(nu + 1):
        t = -1 + 2 * i / nu
        distance = abs(t) * travel
        side = -1 if t < 0 else 1
        for j in range(nv + 1):
            q = -1 + 2 * j / nv
            # Rounded outline corners without a rectangular bent plate.
            rounding = 0.035 * (abs(q) ** 10) * (abs(t) ** 16)
            along = q * (width / 2 - rounding)
            if distance <= half - shoulder:
                across = side * distance
                hit = ray(across, along)
                if hit is None:
                    raise ValueError('Missing support ray inside bed footprint')
                fold = .003 + .002 * math.sin(24 * along + 3 * t) ** 2
                p = Vector(hit) + Vector((0, 0, fold))
                supported.append(len(verts))
            else:
                edge = ray(side * (half - shoulder), along)
                if edge is None:
                    raise ValueError('Missing shoulder support')
                s = distance - (half - shoulder)
                angle = min(math.pi / 2, s / shoulder)
                across = side * (half - shoulder + shoulder * math.sin(angle))
                drop = shoulder * (1 - math.cos(angle)) + max(0, s - shoulder * math.pi / 2)
                wave = (.009 + ease) * math.sin(q * 11 + 1.3) * min(1, s / .08)
                p = Vector(ray.point(across + side * wave, along, 0))
                p.z = edge.z + .004 - drop + .008 * math.sin(q * 9) * (s / (hang + shoulder)) ** 3
                # A duvet can extend far past the mattress rail. Follow that
                # outer shoulder instead of dropping through its hanging side.
                probe = across + side * wave
                for step in range(121):
                    support = ray(probe, along)
                    if support is None or support.z <= p.z - .003:
                        break
                    probe += side * .005
                else:
                    raise ValueError('Cannot clear the outer duvet shoulder')
                shifted = Vector(ray.point(probe + side * .003, along, 0))
                p.x, p.y = shifted.x, shifted.y
            verts.append(tuple(p))
    for i in range(nu):
        for j in range(nv):
            a = i * (nv + 1) + j
            faces.append((a, a + nv + 1, a + nv + 2, a + 1))
    # Callback axes can be either handedness; always keep the cloth top up.
    centre = (nu // 2) * (nv + 1) + nv // 2
    normal = (Vector(verts[centre + nv + 1]) - Vector(verts[centre])).cross(
        Vector(verts[centre + 1]) - Vector(verts[centre]))
    if normal.z < 0:
        faces = [tuple(reversed(face)) for face in faces]
    mesh = bpy.data.meshes.new('RayDrapedStripMesh')
    mesh.from_pydata(verts, [], faces)
    mesh.update()
    obj = bpy.data.objects.new('apt_RayDrapedStrip', mesh)
    bpy.context.collection.objects.link(obj)
    for poly in mesh.polygons:
        poly.use_smooth = True
    solid = obj.modifiers.new('Cloth thickness 2mm', 'SOLIDIFY')
    solid.thickness, solid.offset = .002, -1
    obj['contact_vertices'] = supported
    obj['cloth_width_m'], obj['cloth_hang_m'] = width, hang
    obj['design_top_gap_max_m'] = .005
    return obj
