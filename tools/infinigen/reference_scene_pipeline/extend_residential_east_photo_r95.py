"""East facade finite photo pilot from retained92; no held stone/light changes."""
import bpy,json,hashlib,math
from pathlib import Path
from mathutils import Matrix,Vector
R=Path(__file__).resolve().parents[3]
D=R/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03'
B=R/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full'
source=B/'scene_candidate_r92.blend';out=B/'scene_candidate_r95.blend';assert not out.exists()
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
before_sha=sha(source)
photo=json.loads((D/'realism_refinement_r83.json').read_text())
bpy.ops.wm.open_mainfile(filepath=str(source))
existing={o.name:([list(v) for v in o.matrix_world],o.data.name if o.data else None) for o in bpy.context.scene.objects}
west=bpy.data.objects[photo['plate_object']]
assert west.get('environment_asset') and west.type=='MESH'
east=west.copy();east.data=west.data.copy();east.name='R95_Seoul_east_photo_plate'
bpy.context.scene.collection.objects.link(east)
center=Vector((10.75,9,0))
east.matrix_world=Matrix.Translation(center)@Matrix.Rotation(math.pi,4,'Z')@Matrix.Translation(-center)@west.matrix_world
east['candidate_scope']='East-side finite LDR photo pilot. Same source photograph as west, not continuous panorama, HDR,3D city or all-window solution.'
bpy.context.view_layer.update()
for name,signature in existing.items():
    obj=bpy.data.objects[name]
    assert signature==([list(v) for v in obj.matrix_world],obj.data.name if obj.data else None),name
points=[east.matrix_world@v.co for v in east.data.vertices]
assert all(abs(p.x-66.5)<1e-3 for p in points)
materials=[m for m in east.data.materials if m];assert materials
assert all(not any(n.type in ['EMISSION','LIGHT_PATH'] for n in m.node_tree.nodes) for m in materials)
bpy.ops.wm.save_as_mainfile(filepath=str(out));assert sha(source)==before_sha
meta=json.loads((D/'realism_refinement_r92.json').read_text())
meta.update(source=str(source),source_sha256=before_sha,candidate=str(out),candidate_sha256=sha(out),
    change='Add only an east-side all-ray finite photo surface copied from retained west Seoul plate, atX66.5m. Existing objects/data assignments/transforms,world,lights and cameras preserved. No held91/93/94 changes inherited.',
    east_photo={'object':east.name,'source_object':west.name,'west_source_metadata':'realism_refinement_r83.json',
        'existing_objects_transform_and_data_assignment_count':len(existing),'material_names':[m.name for m in materials],
        'bounds_m':{axis:[min(p[k] for p in points),max(p[k] for p in points)] for k,axis in enumerate('xyz')},
        'attribution':photo['exterior_photo_provenance'],
        'limitation':'Same captured photograph reused on opposite facade; not a continuous panorama, different city view or geometric parallax. North/south windows not addressed. LDR diffuse surface can affect rays/light; fixed-camera regression review required.'},
    photorealism_accepted=False)
(D/'realism_refinement_r95.json').write_text(json.dumps(meta,indent=2))
print('EAST_PHOTO95_SAVED',len(existing),flush=True)
