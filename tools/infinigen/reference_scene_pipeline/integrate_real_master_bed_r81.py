"""One actual bed-assembly trial from retained77; preserve lighting and other rooms."""
import hashlib
import json
from pathlib import Path

import bpy
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

ROOT = Path(__file__).resolve().parents[3]
REF = ROOT / 'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03'
BASE = ROOT / 'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full'
SOURCE, OUTPUT = BASE / 'scene_candidate_r77.blend', BASE / 'scene_candidate_r81.blend'
PROTOTYPE = REF / 'real_bed_candidates/review_studio.blend'
ASSET = 'HSSD_7f6e6db8a0b89d1f055e46dec741245cb390c1ab'
digest = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
assert not OUTPUT.exists()
source_hash, prototype_hash = digest(SOURCE), digest(PROTOTYPE)
scope = json.loads((REF / 'real_bed_candidates/review_scope.json').read_text())
row = next(x for x in scope['assets'] if x['id'] == ASSET)
assert len(row['objects']) == 5
bpy.ops.wm.open_mainfile(filepath=str(SOURCE))
bpy.context.view_layer.update()
scene = bpy.context.scene
old = [o for o in scene.objects if o.get('program_key') == '101_master_bed']
duvet = [o for o in scene.objects if o.get('program_key') == '101_master_bed_draped_duvet']
assert len(old) == len(duvet) == 1
old = old[0]
assert not old.children and not duvet[0].children
properties = {k: old[k] for k in old.keys()}
old_name = old.name


def bounds(obj):
    points = [obj.matrix_world @ Vector(p) for p in obj.bound_box]
    return (Vector(tuple(min(p[k] for p in points) for k in range(3))),
            Vector(tuple(max(p[k] for p in points) for k in range(3))))


def tree(obj):
    evaluated = obj.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    result = BVHTree.FromPolygons([obj.matrix_world @ v.co for v in mesh.vertices],
                                 [tuple(f.vertices) for f in mesh.polygons])
    evaluated.to_mesh_clear()
    return result


old_lo, old_hi = bounds(old)
unexpected = []
for obj in scene.objects:
    if obj in [old, duvet[0]] or obj.type not in ('MESH', 'CURVE'):
        continue
    lo, hi = bounds(obj)
    center = (lo + hi) * .5
    if all(old_lo[k] + .01 < center[k] < old_hi[k] - .01 for k in range(3)):
        unexpected.append({'object': obj.name, 'role': obj.get('program_key')})
assert not unexpected, ('Unaccounted old-bed-region assembly parts', unexpected)

with bpy.data.libraries.load(str(PROTOTYPE), link=False) as (available, loaded):
    loaded.objects = row['objects']
objects = loaded.objects
assert len(objects) == 5 and all(o and o.type == 'MESH' for o in objects)
for obj in objects:
    scene.collection.objects.link(obj)
bpy.context.view_layer.update()
for obj in objects:
    world = obj.matrix_world.copy()
    obj.data = obj.data.copy()
    obj.data.transform(world)
    obj.parent = None
    obj.matrix_world = Matrix.Identity(4)
bpy.ops.object.select_all(action='DESELECT')
for obj in objects:
    obj.select_set(True)
bpy.context.view_layer.objects.active = objects[0]
bpy.ops.object.join()
bed = bpy.context.object
points = [v.co for v in bed.data.vertices]
lo = Vector(tuple(min(v[k] for v in points) for k in range(3)))
hi = Vector(tuple(max(v[k] for v in points) for k in range(3)))
assert max(abs((hi-lo)[k] - row['extents_m'][k]) for k in range(3)) < 1e-4
bed.data.transform(Matrix.Translation(Vector((-(lo.x+hi.x)/2, -hi.y, -lo.z))))
bed.location = ((old_lo.x+old_hi.x)/2, old_hi.y, old_lo.z)
bpy.context.view_layer.update()
new_lo, new_hi = bounds(bed)
assert abs(new_hi.y-old_hi.y) < 1e-5
assert abs(new_lo.z-old_lo.z) < 1e-5

manifest = json.loads((REF / 'real_bed_candidates/asset_candidates_manifest.json').read_text())
entry = next(x for x in manifest['assets'] if x['id'] == ASSET)
expected = {x['sha256'] for x in entry['dependencies'] if x['uri'].startswith('textures/')}
actual = set()
for mat in bed.data.materials:
    assert mat and mat.use_nodes
    for node in mat.node_tree.nodes:
        if node.type == 'TEX_IMAGE' and node.image:
            assert node.image.packed_file
            actual.add(hashlib.sha256(node.image.packed_file.data).hexdigest())
assert actual == expected

floors = []
for obj in scene.objects:
    if obj.type != 'MESH' or not obj.name.endswith('.floor'):
        continue
    flo, fhi = bounds(obj)
    center = (new_lo + new_hi)*.5
    if flo.x < center.x < fhi.x and flo.y < center.y < fhi.y and abs(fhi.z-new_lo.z) < .01:
        floors.append(obj)
assert len(floors) == 1, [o.name for o in floors]
floor_tree = tree(floors[0])
world_points = [bed.matrix_world @ v.co for v in bed.data.vertices]
contacts = [p for p in world_points if p.z < new_lo.z+.001]
assert contacts
contact_gaps = []
for point in contacts:
    hit = floor_tree.ray_cast(point + Vector((0, 0, .1)), Vector((0, 0, -1)), .3)[0]
    assert hit is not None
    contact_gaps.append(point.z-hit.z)
assert max(abs(x) for x in contact_gaps) < .002

for key, value in properties.items():
    bed[key] = value
bed['original_asset_id'] = ASSET
bed['original_asset_sha256'] = row['source_sha256']
bed['room_trial_source_revision'] = 77
removed = [old.name, duvet[0].name]
for obj in [old, duvet[0]]:
    bpy.data.objects.remove(obj, do_unlink=True)
bed.name = old_name
bpy.context.view_layer.update()
bed_tree = tree(bed)
collisions = []
for obj in scene.objects:
    if obj == bed or obj.type != 'MESH' or obj.hide_render:
        continue
    is_check = obj.get('program_key') == '101_master_nightstand' or obj.name.endswith(('.wall', '.exterior'))
    if not is_check:
        continue
    a, b = bounds(obj)
    if any(new_hi[k] < a[k] or new_lo[k] > b[k] for k in range(3)):
        continue
    overlaps = bed_tree.overlap(tree(obj))
    collisions.append({'object': obj.name, 'surface_triangle_intersections': len(overlaps)})
    assert not overlaps, collisions
assert digest(SOURCE) == source_hash and digest(PROTOTYPE) == prototype_hash
bpy.ops.wm.save_as_mainfile(filepath=str(OUTPUT))
views = [v for v in json.loads((BASE / 'review_views_fine_r73.json').read_text()) if v['name'] == '101_master']
views.append({'name': '101_master_bed_drape_detail', 'location': [5.95, 15.05, 1.1],
              'target': [7.0, 16.55, .70], 'hfov': 65})
(BASE / 'review_views_master_bed_r81.json').write_text(json.dumps(views, indent=2)+'\n')
metadata = {'source': str(SOURCE), 'source_sha256': source_hash, 'candidate': str(OUTPUT),
            'candidate_sha256': digest(OUTPUT), 'prototype': str(PROTOTYPE), 'prototype_sha256': prototype_hash,
            'asset_id': ASSET, 'native_parts_joined': 5, 'native_extents_m': row['extents_m'],
            'new_world_bounds': [list(new_lo), list(new_hi)], 'head_y_anchor': old_hi.y,
            'old_parts_removed': removed, 'unaccounted_old_parts': unexpected,
            'floor': floors[0].name, 'bottom_vertices_checked': len(contacts),
            'max_absolute_floor_gap_m': max(abs(x) for x in contact_gaps),
            'surface_intersections': collisions, 'original_packed_images_verified': True,
            'scale_changed': False, 'retained_revision': 77, 'photorealism_accepted': False,
            'change': 'Actual5-part product bed assembly replaces101 master body+duvet only. Rigid head-wall/floor anchoring;nativegeometry/UV/materials retained. Other furnishings,lights/world/exposure unchanged.',
            'limitations': 'Grey palette andmissing accent cushions remain off-reference. Source material roughness inferred,not measured. Surface/floor checks arebounded;not closed-volume/all-room/navigation/photo acceptance. Source77 baseline pair andfresh review required.'}
(REF / 'realism_refinement_r81.json').write_text(json.dumps(metadata, indent=2)+'\n')
print('REAL_MASTER_BED_R81_SAVED', flush=True)
