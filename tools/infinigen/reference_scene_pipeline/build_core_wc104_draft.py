"""New, explicitly unaccepted architectural draft from immutable residential103.

Replace conflicting wall apertures; add two real native WC/basin/door assemblies.
Architectural solids are authored wall construction, not product stand-ins.
"""
import bpy
import bmesh
import copy
import hashlib
import json
import math
import sys
from pathlib import Path
from mathutils import Matrix, Vector
from shapely.geometry import box
from shapely.ops import triangulate

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(Path(__file__).parent))
from wc_layout_checks import bounds

D = ROOT / 'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03'
P = D / 'core_wc104_planning'
B = ROOT / 'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full'
S, O = B / 'scene_candidate_r103.blend', B / 'scene_candidate_r104_draft.blend'
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()


def clip_half(poly, axis, bound, keep_less):
    """Convex polygon clipping with per-loop UV interpolation."""
    result = []
    for a, b in zip(poly, poly[1:] + poly[:1]):
        va, vb = a[0][axis] - bound, b[0][axis] - bound
        ia = va <= 1e-10 if keep_less else va >= -1e-10
        ib = vb <= 1e-10 if keep_less else vb >= -1e-10
        if ia:
            result.append(a)
        if ia != ib:
            t = va / (va - vb)
            result.append((a[0].lerp(b[0], t),
                           [u.lerp(v, t) for u, v in zip(a[1], b[1])]))
    unique = []
    for item in result:
        if not unique or (item[0] - unique[-1][0]).length > 1e-8:
            unique.append(item)
    if len(unique) > 1 and (unique[0][0] - unique[-1][0]).length < 1e-8:
        unique.pop()
    return unique if len(unique) >= 3 else []


def subtract_box(poly, lo, hi):
    pending, output = poly, []
    for axis in range(3):
        for bound, inside_less in [(lo[axis], False), (hi[axis], True)]:
            if not pending:
                return output
            outside = clip_half(pending, axis, bound, not inside_less)
            if outside:
                output.append(outside)
            pending = clip_half(pending, axis, bound, inside_less)
    return output


def cut_architecture(obj, cuts):
    old = obj.data
    uv_layers = list(old.uv_layers)
    inverse = obj.matrix_world.inverted()
    verts, faces, materials, smooth, uv_values = [], [], [], [], []
    changed = 0
    for face in old.polygons:
        poly = [(obj.matrix_world @ old.vertices[old.loops[i].vertex_index].co,
                 [layer.data[i].uv.copy() for layer in uv_layers])
                for i in face.loop_indices]
        pieces = [poly]
        for lo, hi in cuts:
            next_pieces = []
            for piece in pieces:
                if any(max(v[0][k] for v in piece) < lo[k] - 1e-8 or
                       min(v[0][k] for v in piece) > hi[k] + 1e-8 for k in range(3)):
                    next_pieces.append(piece)
                else:
                    next_pieces.extend(subtract_box(piece, lo, hi))
                    changed += 1
            pieces = next_pieces
        for piece in pieces:
            ids = tuple(range(len(verts), len(verts) + len(piece)))
            # Reject collapsed boundary remnants.
            area = sum((piece[j][0]-piece[0][0]).cross(piece[j+1][0]-piece[0][0]).length
                       for j in range(1, len(piece)-1)) / 2
            if area < 1e-10:
                continue
            verts.extend(tuple(inverse @ v[0]) for v in piece)
            faces.append(ids)
            uv_values.append([v[1] for v in piece])
            materials.append(face.material_index)
            smooth.append(face.use_smooth)
    if not changed:
        return None
    mesh = bpy.data.meshes.new(old.name + '_core104_clip')
    mesh.from_pydata(verts, [], faces)
    for mat in old.materials:
        mesh.materials.append(mat)
    for i, face in enumerate(mesh.polygons):
        face.material_index, face.use_smooth = materials[i], smooth[i]
    for layer_index, layer in enumerate(uv_layers):
        target = mesh.uv_layers.new(name=layer.name)
        for face_index, face in enumerate(mesh.polygons):
            for corner, loop in enumerate(face.loop_indices):
                target.data[loop].uv = uv_values[face_index][corner][layer_index]
    mesh.update()
    obj.data = mesh
    return {'object': obj.name, 'old_faces': len(old.polygons),
            'new_faces': len(mesh.polygons), 'intersected_face_pieces': changed,
            'uv_layers_preserved': [l.name for l in uv_layers],
            'scope': 'World-space convex clipping with interpolated loop UV; architecture mesh attributes/custom normals not propagated.'}


def solid(name, polygon, axis, lower, upper, material):
    """Extrude a planar architectural domain, including aperture reveals."""
    rings = [list(polygon.exterior.coords)[:-1]] + [list(r.coords)[:-1] for r in polygon.interiors]
    coords = [p for ring in rings for p in ring]
    lookup = {tuple(round(c, 8) for c in p): i for i, p in enumerate(coords)}
    n = len(coords)
    def point(p, depth):
        return (depth, p[0], p[1]) if axis == 0 else (p[0], depth, p[1])
    vertices = [point(p, depth) for depth in (lower, upper) for p in coords]
    faces = []
    for tri in triangulate(polygon):
        if not polygon.covers(tri):
            continue
        indices = [lookup[tuple(round(c, 8) for c in p)] for p in list(tri.exterior.coords)[:-1]]
        faces += [tuple(reversed(indices)), tuple(i+n for i in indices)]
    offset = 0
    for ring in rings:
        for j in range(len(ring)):
            i, k = offset+j, offset+(j+1) % len(ring)
            faces.append((i, k, k+n, i+n))
        offset += len(ring)
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices, [], faces)
    mesh.materials.append(material)
    bm = bmesh.new(); bm.from_mesh(mesh)
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    bm.to_mesh(mesh); bm.free()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj['program_key'] = name
    obj['audit_kind'] = 'architecture'
    obj['reference_scene_owner'] = 'dual_unit_residential_floor_03'
    uv = mesh.uv_layers.new(name='physical_world_metres')
    for face in mesh.polygons:
        dominant = max(range(3), key=lambda k: abs(face.normal[k]))
        axes = [k for k in range(3) if k != dominant]
        for li in face.loop_indices:
            p = mesh.vertices[mesh.loops[li].vertex_index].co
            uv.data[li].uv = (p[axes[0]], p[axes[1]])
    return obj


def main():
    assert not O.exists(), 'Preserve every previous candidate/draft'
    source_sha = sha(S)
    bpy.ops.wm.open_mainfile(filepath=str(S))
    fz = bounds(bpy.data.objects['hallway_0/1.floor'])[1].z
    cz = bounds(bpy.data.objects['hallway_0/1.ceiling'])[0].z
    wall_mat = bpy.data.materials['ReferencePBR_roller_painted_plaster']
    cuts = []
    for x in (9, 12.5):
        cuts.append(((x-.1156, 6, fz-.002), (x+.1156, 9.5, cz+.002)))
    cut_records = []
    for obj in list(bpy.context.scene.objects):
        if obj.type != 'MESH' or not (obj.name.endswith(('.wall', '.exterior')) or obj.name == 'skirtingboard_support'):
            continue
        record = cut_architecture(obj, cuts)
        if record:
            cut_records.append(record)
    assert {r['object'] for r in cut_records} >= {'hallway_0/1.wall', 'hallway_0/4.wall', 'hallway_0/7.wall'}
    doors = [(101, 'GlassPanelDoorFactory(1275309).spawn_asset(11)', 'DoorCasingFactory(1275309).spawn_asset(11)', 'door.010'),
             (102, 'LiteDoorFactory(7699791).spawn_asset(12)', 'DoorCasingFactory(7699791).spawn_asset(12)', 'door.021')]
    moved = []
    for unit, door_name, casing_name, helper_name in doors:
        casing = bpy.data.objects[casing_name]
        lo, hi = bounds(casing)
        delta = 6.75 - (lo.y+hi.y)/2
        for name in [door_name, casing_name, helper_name]:
            obj = bpy.data.objects[name]
            matrix = obj.matrix_world.copy(); matrix.translation.y += delta; obj.matrix_world = matrix
        # Fit opening to native frame. Single-column glass uses original aperture width.
        width = .911587 if unit == 101 else hi.y-lo.y-.040
        low, high = 6.75-width/2, 6.75+width/2
        x = 9 if unit == 101 else 12.5
        domain = box(6, fz, 9.5, cz).difference(box(low, fz-.01, high, 2.4699543))
        solid(f'Core104_{unit}_relocated_entrance_wall', domain, 0, x-.1145347, x+.1145347, wall_mat)
        moved.append({'unit': unit, 'door': door_name, 'delta_y_m': delta, 'opening_y_m': [low, high]})
    # New internal partitions: mirror positions, not product geometry.
    for unit in (101, 102):
        x0, x1 = (7.7854653, 8.0145347) if unit == 101 else (13.4854653, 13.7145347)
        domain = box(7.3854653, fz, 9.3854653, cz).difference(box(7.733, fz-.01, 8.767, fz+2.380))
        solid(f'Core104_{unit}_WC_side_wall', domain, 0, x0, x1, wall_mat)
        xs = (7.7854653, 8.8854653) if unit == 101 else (12.6145347, 13.7145347)
        solid(f'Core104_{unit}_WC_south_wall', box(xs[0], fz, xs[1], cz), 1, 7.3854653, 7.6145347, wall_mat)
    # Native full adult toilet product already validated in r103; no scale change.
    contract = json.loads((D/'native_fullsize_wc100/contract.json').read_text())
    assert sha(contract['prototype_source']) == contract['prototype_source_sha256']
    with bpy.data.libraries.load(contract['prototype_source'], link=False) as (src, dst):
        dst.objects = [contract['object']]
    toilet = dst.objects[0]
    bpy.context.scene.collection.objects.link(toilet)
    toilets = []
    for unit in (101, 102):
        obj = toilet if unit == 101 else toilet.copy()
        if unit == 102:
            bpy.context.scene.collection.objects.link(obj)
        obj.name = f'Residential03_{unit}_core_wc_native_toilet'
        obj.parent = None; obj.matrix_world = Matrix.Identity(4)
        obj.rotation_euler.z = -math.pi/2
        bpy.context.view_layer.update()
        lo, hi = bounds(obj)
        cx = 8.45 if unit == 101 else 13.05
        obj.location += Vector((cx-(lo.x+hi.x)/2, 9.365-hi.y, fz-lo.z))
        obj['program_key'] = f'{unit}_core_wc_wc'
        obj['audit_kind'] = 'furniture'
        obj['native_factory_product'] = 'native_fullsize_wc100'
        obj['reference_scene_owner'] = 'dual_unit_residential_floor_03'
        toilets.append(obj.name)
    # Append original basin/faucet/drain meshes from the native-byte audited studio.
    studio = json.loads((P/'review_scope.json').read_text())
    row = next(r for r in studio['assets'] if '05dfa289' in r['id'])
    with bpy.data.libraries.load(str(P/'review_studio.blend'), link=False) as (src, dst):
        dst.objects = row['objects']
    originals = dst.objects
    for obj in originals:
        bpy.context.scene.collection.objects.link(obj)
    original_basin_matrices = [o.matrix_world.copy() for o in originals]
    basins = []
    for unit in (101, 102):
        objects = originals if unit == 101 else [o.copy() for o in originals]
        if unit == 102:
            for obj in objects:
                bpy.context.scene.collection.objects.link(obj)
        for obj, original_matrix in zip(objects, original_basin_matrices):
            obj.parent = None
            obj.matrix_world = Matrix.Rotation(math.pi, 4, 'Z') @ original_matrix
        bpy.context.view_layer.update()
        bb = [bounds(o) for o in objects]
        lo = Vector(tuple(min(a[k] for a,b in bb) for k in range(3)))
        hi = Vector(tuple(max(b[k] for a,b in bb) for k in range(3)))
        ceramic_profile_keys = [m['name'] for m in row['material_metadata']
                                if 'ceramic' in m.get('rule_id', '')]
        assert len(ceramic_profile_keys) == 1
        ceramic = next(o for o in objects if any(
            m and m.name.startswith(ceramic_profile_keys[0]) for m in o.data.materials))
        rim = bounds(ceramic)[1].z
        cx = 8.87-(hi.x-lo.x)/2 if unit == 101 else 12.63+(hi.x-lo.x)/2
        shift = Vector((cx-(lo.x+hi.x)/2, 7.616-lo.y, fz+.85-rim))
        for obj in objects:
            obj.location += shift
            obj.name = f'Residential03_{unit}_core_wc_native_basin_' + obj.name
            obj['program_key'] = f'{unit}_core_wc_vanity'
            obj['audit_kind'] = 'furniture'
            obj['original_asset_id'] = row['id']
        basins += [o.name for o in objects]
    # Native framed slab and lever, outward toward existing wide living opening.
    prototype = ROOT/'data/venue_refs/floor_plans_v3/commercial_office_floor_02/native_flat_door_pilot02/asset.blend'
    with bpy.data.libraries.load(str(prototype), link=False) as (src, dst):
        dst.objects = ['Office02_native_flat_leaf_full_frame_lever']
    native = dst.objects[0]
    bpy.context.scene.collection.objects.link(native)
    native_raw_mesh = native.data
    wc_doors = []
    for unit in (101, 102):
        obj = native if unit == 101 else native.copy()
        if unit == 102:
            bpy.context.scene.collection.objects.link(obj)
        obj.data = native_raw_mesh.copy()
        obj.name = f'Residential03_{unit}_core_wc_native_door'
        # Unit102 mirrors rigid pose; normals/mesh scales remain positive.
        wallx = 7.9 if unit == 101 else 13.6
        rotation = math.pi/2
        obj.matrix_world = Matrix.Translation(Vector((wallx,8.25,fz))) @ Matrix.Rotation(rotation,4,'Z')
        moving = {i for f in obj.data.polygons if obj.data.materials[f.material_index].name.split('.')[0] != 'office02_charcoal' for i in f.vertices}
        # Keep native handle opposite its hinge; reverse opening direction only.
        hinge_local_x = .475
        pivot = obj.matrix_world @ Vector((hinge_local_x,0,0))
        delta = -math.pi/2 if unit == 101 else math.pi/2
        transform = obj.matrix_world.inverted() @ Matrix.Translation(pivot) @ Matrix.Rotation(delta,4,'Z') @ Matrix.Translation(-pivot) @ obj.matrix_world
        normals = [v.vector.copy() for v in obj.data.corner_normals] if obj.data.has_custom_normals else None
        for i in moving:
            obj.data.vertices[i].co = transform @ obj.data.vertices[i].co
        obj.data.update()
        if normals:
            normal_matrix = transform.to_3x3().inverted().transposed()
            for loop in obj.data.loops:
                if loop.vertex_index in moving:
                    normals[loop.index] = (normal_matrix @ normals[loop.index]).normalized()
            obj.data.normals_split_custom_set(normals)
        obj['program_key'] = f'{unit}_core_wc_door'
        obj['audit_kind'] = 'furniture'
        obj['core104_hinge_world_m'] = list(pivot)
        obj['core104_open_angle_deg'] = math.degrees(delta)
        obj['native_source_asset'] = str(prototype)
        wc_doors.append(obj.name)
    bpy.context.view_layer.update()
    assert len([o for o in bpy.context.scene.objects if str(o.get('program_key','')).endswith('_wc') and o.type=='MESH']) == 10
    assert sha(S) == source_sha
    bpy.ops.wm.save_as_mainfile(filepath=str(O))
    report = {'source':str(S), 'source_sha256':source_sha, 'draft':str(O), 'draft_sha256':sha(O),
              'architecture_clips':cut_records, 'relocated_entrances':moved,
              'new_native_toilets':toilets, 'new_native_basin_objects':basins,
              'new_native_doors':wc_doors, 'native_toilet_count':10,
              'status':'UNACCEPTED_DRAFT_REQUIRES_SOURCE_AND_RGB_AUDITS',
              'open_items':['Door mirrored moving selection and all normals need saved-source checks.',
                            'Actual native door sweep, casing and 600mm path; all ten WC source-bound audit.',
                            'New WC floor/wall finishes and plumbing/mounting/lighting not yet authored.',
                            'Canonical plans and full-suite gate still describe eight current approved-for-review products; update alongside verified new architecture.'],
              'photorealism_accepted':False,'dataset_promoted':False}
    (P/'draft_build.json').write_text(json.dumps(report,indent=2)+'\n')
    print('CORE_WC104_DRAFT_SAVED',str(O),flush=True)


if __name__ == '__main__':
    main()
