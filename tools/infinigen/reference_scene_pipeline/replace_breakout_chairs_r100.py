"""Actual curved upholstered dining-chair trial in breakout only; source98 preserved."""
import bpy, json, math, hashlib
from pathlib import Path
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

ROOT = Path(__file__).resolve().parents[3]
REF = ROOT/'data/venue_refs/floor_plans_v3/commercial_office_floor_02'
BASE = ROOT/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full'
source = BASE/'scene_candidate_r98.blend'
out = BASE/'scene_candidate_r100.blend'
prototype = REF/'real_breakout_chair_candidates/aac23_blue_wood_variant/review_studio.blend'
assert not out.exists()
sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
source_sha, prototype_sha = sha(source), sha(prototype)
bpy.ops.wm.open_mainfile(filepath=str(source))
prefixes = ('breakout_chair_',)
old = [o for o in bpy.data.objects if str(o.get('program_key','')).startswith(prefixes)
       and o.get('audit_kind')=='furniture' and o.parent is None]
assert len(old) == 4
legacy_children=[child for obj in old for child in obj.children_recursive]
assert len(legacy_children)==64 and len(set(legacy_children))==64
legacy_names=[obj.name for obj in old+legacy_children]
semantic_keys={'reference_scene_owner','program_key','room_id','support_room_id','audit_kind','semantic'}
placements = [(o.name, str(o['program_key']), o.matrix_world.translation.copy(),
               {key:value for key,value in o.items() if key in semantic_keys}) for o in old]
names = json.loads((REF/'real_breakout_chair_candidates/aac23_blue_wood_variant/provenance.json').read_text())['object_names']
with bpy.data.libraries.load(str(prototype), link=False) as (src, dst):
    dst.objects = names
parts = dst.objects
assert len(parts) == 3 and all(o and o.type == 'MESH' for o in parts)
for o in parts:
    bpy.context.scene.collection.objects.link(o)
bpy.context.view_layer.update()
# Bake only rigid studio transforms; original vertices, polygons and UVs survive.
for o in parts:
    world = o.matrix_world.copy()
    assert abs(world.to_3x3().determinant()-1) < 1e-4
    o.data = o.data.copy()
    o.data.transform(world)
    o.parent = None
    o.matrix_world = Matrix.Identity(4)
points = [v.co for o in parts for v in o.data.vertices]
lo = Vector(tuple(min(v[k] for v in points) for k in range(3)))
hi = Vector(tuple(max(v[k] for v in points) for k in range(3)))
assert .75 < hi.z-lo.z < .85
normalize = Matrix.Translation(Vector((-(lo.x+hi.x)/2, -(lo.y+hi.y)/2, -lo.z)))
for o in parts:
    o.data.transform(normalize)
floor_objects = [o for o in bpy.data.objects if o.type == 'MESH' and o.name.endswith('.floor')]
floor_points, floor_polys = [], []
for o in floor_objects:
    offset = len(floor_points)
    floor_points += [o.matrix_world@v.co for v in o.data.vertices]
    floor_polys += [tuple(offset+i for i in p.vertices) for p in o.data.polygons]
floor_tree = BVHTree.FromPolygons(floor_points, floor_polys)
def tree(objects):
    vertices, polygons = [], []
    for o in objects:
        offset = len(vertices)
        vertices += [o.matrix_world@v.co for v in o.data.vertices]
        polygons += [tuple(offset+i for i in p.vertices) for p in o.data.polygons]
    return BVHTree.FromPolygons(vertices, polygons)
records, installed = [], []
for old_name, key, pos, props in placements:
    hit = floor_tree.ray_cast(Vector((pos.x,pos.y,1)), Vector((0,0,-1)), 2)[0]
    assert hit is not None
    # Native studio chair faces -Y. Both rows face the breakout table at Y=2.
    yaw = math.pi if pos.y < 2 else 0
    group = []
    for i, original in enumerate(parts):
        o = original.copy()
        bpy.context.scene.collection.objects.link(o)
        o.name = f'Office02_r100_{key}_part{i}'
        o.rotation_euler = (0,0,yaw)
        o.location = (pos.x,pos.y,hit.z)
        for k,v in props.items(): o[k] = v
        o['program_key'] = key if i == 0 else key+f'_component{i}'
        o['audit_kind'] = 'furniture' if i == 0 else 'chair_component'
        o['original_asset_id'] = 'HSSD_b033c9e6d7b22928943277cb35ce135cc3d54685'
        o['chair_assembly_key'] = key
        group.append(o)
    installed.append(group)
    bpy.context.view_layer.update()
    bounds = [o.matrix_world@v.co for o in group for v in o.data.vertices]
    gap = min(v.z for v in bounds)-hit.z
    assert abs(gap) < 1e-5
    table_key = key.split('_chair_')[0]+'_table'
    tables = [o for o in bpy.data.objects if o.type == 'MESH' and o.get('program_key') == table_key]
    assert tables
    intersections = len(tree(group).overlap(tree(tables)))
    assert intersections == 0, (key, intersections)
    records.append({'role':key,'removed':old_name,'parts':[o.name for o in group],
        'floor_hit':list(hit),'floor_gap_m':gap,'yaw_rad':yaw,
        'native_extent_m':list(hi-lo),'scale_changed':False,
        'part_geometry_sha256':{o.name:hashlib.sha256(repr(([tuple(v.co) for v in o.data.vertices],[tuple(p.vertices) for p in o.data.polygons],[[tuple(x.uv) for x in layer.data] for layer in o.data.uv_layers])).encode()).hexdigest() for o in group},
        'table_triangle_surface_intersections':intersections})
for i, a in enumerate(installed):
    for b in installed[i+1:]:
        assert not tree(a).overlap(tree(b)), 'chair-chair surface intersection'
for o in legacy_children+old+parts: bpy.data.objects.remove(o,do_unlink=True)
bpy.ops.wm.save_as_mainfile(filepath=str(out))
assert sha(source) == source_sha and sha(prototype) == prototype_sha
meta = json.loads((REF/'realism_refinement_r98.json').read_text())
meta.update(source=str(source),source_sha256=source_sha,candidate=str(out),candidate_sha256=sha(out),
    change='Replace only four breakout chairs with actual curved AAC23 upholstery and authored blue/wood response. Native geometry/UV at native scale; all other furniture,world,lights/cameras retained.',
    breakout_chair_prototype=str(prototype),breakout_chair_prototype_sha256=prototype_sha,breakout_chair_records=records,
    removed_breakout_legacy_objects=legacy_names,
    photorealism_accepted=False,
    scope='Rigid placement at native scale. Floor ray/support and actual chair/table plus chair/chair triangle surface checks only; no closed-volume containment, ergonomics, complete door sweep, or navigation certification. Existing source98 audits do not certify source100; saved-source and RGB checks required.')
(REF/'realism_refinement_r100.json').write_text(json.dumps(meta,indent=2))
print('BREAKOUT_DINING_CHAIRS_R100_SAVED',flush=True)
