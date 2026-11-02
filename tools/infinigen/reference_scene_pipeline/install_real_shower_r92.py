"""One bathroom real shower assembly trial; preserve room and reviewed r90 checkpoint."""
import bpy,bmesh,json,hashlib
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree
R=Path(__file__).resolve().parents[3]
D=R/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03'
B=R/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full'
source,out=B/'scene_candidate_r90.blend',B/'scene_candidate_r92.blend'
assert not out.exists()
asset=D/'real_shower_kit_candidate/with_controls'
assert (asset/'blind_visual_review.json').exists()
scope=json.loads((asset/'review_scope.json').read_text())
prototype=asset/'review_studio.blend'
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
source_sha,prototype_sha=sha(source),sha(prototype)
bpy.ops.wm.open_mainfile(filepath=str(source))
old=next(o for o in bpy.data.objects if o.get('program_key')=='101_bathroom2_shower')
components=json.loads((D/'old_shower_components_r90.json').read_text())
assert components['object']==old.name
remove=[components['components'][i] for i in [4,5,6]]
assert [len(c['face_indices']) for c in remove]==[10,18,14]
for row in remove:
    faces=[old.data.polygons[i] for i in row['face_indices']]
    points=[old.data.vertices[i].co for f in faces for i in f.vertices]
    assert {f.material_index for f in faces}=={2}
    assert all(abs(min(p[k] for p in points)-row['lo'][k])<1e-5 and
               abs(max(p[k] for p in points)-row['hi'][k])<1e-5 for k in range(3))
old.data=old.data.copy();before_faces=len(old.data.polygons)
bm=bmesh.new();bm.from_mesh(old.data);bm.faces.ensure_lookup_table()
vertices={v for row in remove for i in row['face_indices'] for v in bm.faces[i].verts}
bmesh.ops.delete(bm,geom=list(vertices),context='VERTS');bm.to_mesh(old.data);bm.free()
assert before_faces-len(old.data.polygons)==42
def tree(objects):
    points,polygons=[],[]
    for o in objects:
        e=o.evaluated_get(bpy.context.evaluated_depsgraph_get());m=e.to_mesh();offset=len(points)
        points.extend(o.matrix_world@v.co for v in m.vertices)
        polygons.extend(tuple(offset+i for i in p.vertices) for p in m.polygons)
        e.to_mesh_clear()
    return BVHTree.FromPolygons(points,polygons)
wall=bpy.data.objects['bathroom_0/2.wall'];wall_tree=tree([wall])
wall_hit=wall_tree.ray_cast(Vector((2.25,5.45,1.6)),Vector((0,1,0)),1)[0]
assert wall_hit is not None and 5.85<wall_hit.y<5.95
floor=bpy.data.objects['bathroom_0/2.floor']
floor_hit=tree([floor]).ray_cast(Vector((2.25,5.5,.5)),Vector((0,0,-1)),1)[0]
assert floor_hit is not None
names=scope['kit_objects']+scope['valve_objects']
with bpy.data.libraries.load(str(prototype),link=False) as (src,dst):dst.objects=list(names)
parts=dst.objects;assert len(parts)==5 and all(o and o.type=='MESH' for o in parts)
for o in parts:bpy.context.scene.collection.objects.link(o)
bpy.context.view_layer.update()
points=[o.matrix_world@v.co for o in parts for v in o.data.vertices]
rear=max(p.y for p in points);bottom=min(p.z for p in points)
delta=Vector((2.25,wall_hit.y-.001-rear,floor_hit.z+.55-bottom))
for i,o in enumerate(parts):
    assert o.parent is None
    o.location+=delta
    o.name=f'Res03_r92_101_bathroom2_actual_shower_{i}'
    o['reference_scene_owner']='dual_unit_residential_floor_03'
    o['program_key']=f'101_bathroom2_shower_actual_hardware_{i}'
    o['audit_kind']='wall_fixture';o['support_object']=wall.name
    o['original_asset_id']='HSSD_9e068412c7ca15a5d23c5813614150ff138d9bb6' if i<4 else 'HSSD_da563ad88ad4606e27514b55efb1032ccd9fa5b2'
bpy.context.view_layer.update()
points=[o.matrix_world@v.co for o in parts for v in o.data.vertices]
lo=Vector(tuple(min(p[k] for p in points) for k in range(3)))
hi=Vector(tuple(max(p[k] for p in points) for k in range(3)))
assert lo.x>1.905 and hi.x<2.855 and lo.y>4.905 and hi.z<2.3
assert abs(wall_hit.y-hi.y-.001)<1e-5
assembly_tree=tree(parts);checks=[]
obstacles=[o for o in bpy.context.scene.objects if o.type=='MESH' and o not in parts and
           (o.name in ['bathroom_0/2.wall','bathroom_0/2.floor','bathroom_0/2.ceiling'] or
            str(o.get('program_key','')).startswith('101_bathroom2'))]
for obstacle in obstacles:
    count=len(assembly_tree.overlap(tree([obstacle])))
    checks.append({'object':obstacle.name,'triangle_surface_intersections':count})
    assert count==0,(obstacle.name,count)
mounts=[p for p in points if p.y>hi.y-.0001]
gaps=[]
for p in mounts:
    hit=wall_tree.ray_cast(p-Vector((0,.002,0)),Vector((0,1,0)),.02)[0]
    assert hit is not None;gaps.append(hit.y-p.y)
assert gaps and max(abs(g-.001) for g in gaps)<.0002
bpy.ops.wm.save_as_mainfile(filepath=str(out))
assert sha(source)==source_sha and sha(prototype)==prototype_sha
meta=json.loads((D/'realism_refinement_r90.json').read_text())
meta.update(source=str(source),source_sha256=source_sha,candidate=str(out),candidate_sha256=sha(out),
    change='One main bathroom: remove only42 faces of legacy primitive head/arm/control, install actual source rain head,handset,rail,hose and separate thermostatic controls. Other room geometry,finishes,world,lights,cameras unchanged. No held91 lighting inherited.',
    real_shower={'prototype':str(prototype),'prototype_sha256':prototype_sha,'objects':[o.name for o in parts],
        'kit_faces':12002,'valve_faces':sum(len(o.data.polygons) for o in parts[4:]),
        'bounds':[list(lo),list(hi)],'translation_only':list(delta),'wall':wall.name,
        'wall_mount_gap_m':.001,'mount_vertex_count':len(gaps),'removed_legacy_faces':42,
        'obstacle_surface_checks':checks},photorealism_accepted=False,
    scope='One bathroom only. Bounds, mounting rays and actual local triangle surface intersections; not full-volume containment,concealed plumbing,waterproofing,mechanical support,door sweep/navigation or reference/photo acceptance.')
(D/'realism_refinement_r92.json').write_text(json.dumps(meta,indent=2))
receipt=json.loads((D/'full_suite_r90/candidate/render_receipt.json').read_text())
views=[f['camera'] for f in receipt['frames'] if f['name'] in ['101_bathroom','101_bathroom_wc_reverse']]
views.append({'name':'101_shower_installed_detail','location':[1.15,4.35,1.7],
              'target':[2.35,5.65,1.4],'hfov':65,'render_width':1280,'samples':48})
(D/'real_shower_r92_views.json').write_text(json.dumps(views,indent=2))
print('REAL_SHOWER_R92_SAVED',len(checks),len(gaps),flush=True)
