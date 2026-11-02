"""Saved source-bound native furniture identity audit; photo acceptance separate."""
import bpy,json,hashlib
from pathlib import Path
from mathutils import Matrix,Vector
r=Path(__file__).resolve().parents[3];d=r/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';a=json.loads((d/'bedroom110_build.json').read_text());fix=json.loads((d/'bedroom111_support_fix.json').read_text());sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest();assert sha(fix['candidate'])==fix['candidate_sha256'];assert sha(fix['source'])==fix['source_sha256'];assert sha(a['prototype'])==a['prototype_sha256'];bpy.ops.wm.open_mainfile(filepath=fix['candidate']);scope=json.loads((d/'bedroom110_products/review_scope.json').read_text());row=next(x for x in scope['assets'] if x['id']=='HSSD_xxxx2d7fa89ax71d3x4ac7xb350xa294dd8ef99b')
with bpy.data.libraries.load(a['prototype'],link=False) as (s,z):z.objects=row['objects']
protos=z.objects
for o in protos:bpy.context.scene.collection.objects.link(o)
bpy.context.view_layer.update();points=[o.matrix_world@v.co for o in protos for v in o.data.vertices];lo=Vector([min(v[k] for v in points) for k in range(3)]);hi=Vector([max(v[k] for v in points) for k in range(3)]);delta=Vector((-(lo.x+hi.x)/2,-(lo.y+hi.y)/2,-lo.z));rows=[]
for replace in a['replacements']:
 for name,proto in zip(replace['new_objects'],protos):
  o=bpy.data.objects[name];expected=[delta+proto.matrix_world@v.co for v in proto.data.vertices];assert len(expected)==len(o.data.vertices);err=max((v.co-q).length for v,q in zip(o.data.vertices,expected));assert err<1e-6;assert all(abs(x-1)<1e-6 for x in o.scale);assert [tuple(f.vertices) for f in o.data.polygons]==[tuple(f.vertices) for f in proto.data.polygons];assert [f.material_index for f in o.data.polygons]==[f.material_index for f in proto.data.polygons]
  assert len(o.data.uv_layers)==len(proto.data.uv_layers)
  for x,y in zip(o.data.uv_layers,proto.data.uv_layers):assert len(x.data)==len(y.data) and max((u.uv-v.uv).length for u,v in zip(x.data,y.data))<1e-7
  rows.append({'object':name,'native_coordinate_error_m':err,'scale':list(o.scale),'native_topology_uv_material_indices_match':True})
 assert replace['old_object'] not in bpy.data.objects
(d/'bedroom111_native_saved_audit.json').write_text(json.dumps({'pass':True,'candidate_sha256':fix['candidate_sha256'],'objects':rows,'scope':'Saved native geometry/topology/UV/material-index preservation and unit scale, obsolete box stands absent. No material-graph equivalence, whole navigation or visual approval.'},indent=2));print('BEDROOM111_NATIVE_SAVED_AUDIT_PASS')
