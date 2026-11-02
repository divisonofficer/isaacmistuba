"""Reopen r112 and compare native product topology/UVs; no photo acceptance."""
import bpy,json,hashlib
from pathlib import Path
from mathutils import Matrix,Vector
r=Path(__file__).resolve().parents[3];d=r/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';m=json.loads((d/'taskchairs112_build.json').read_text());sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
assert sha(m['candidate'])==m['candidate_sha256'];assert sha(m['source'])==m['source_sha256'];assert sha(m['prototype_studio'])==m['prototype_studio_sha256']
bpy.ops.wm.open_mainfile(filepath=m['candidate'])
with bpy.data.libraries.load(m['prototype_studio'],link=False) as (a,z):z.objects=['B06W5XBL3D.001']
p=z.objects[0];bpy.context.scene.collection.objects.link(p);bpy.context.view_layer.update();native=[p.matrix_world@v.co for v in p.data.vertices];lo=Vector([min(v[k] for v in native) for k in range(3)]);hi=Vector([max(v[k] for v in native) for k in range(3)]);offset=Vector((-(lo.x+hi.x)/2,-(lo.y+hi.y)/2,-lo.z));native=[v+offset for v in native]
rows=[]
for row in m['replaced_chairs']:
 o=next(x for x in bpy.context.scene.objects if x.get('program_key')==row['key']);assert o['original_asset_id']==m['native_asset'];assert all(abs(v-1)<1e-6 for v in o.scale);assert len(o.data.vertices)==len(native);err=max((v.co-q).length for v,q in zip(o.data.vertices,native));assert err<1e-6
 assert [tuple(f.vertices) for f in o.data.polygons]==[tuple(f.vertices) for f in p.data.polygons]
 assert [f.material_index for f in o.data.polygons]==[f.material_index for f in p.data.polygons]
 assert len(o.data.uv_layers)==len(p.data.uv_layers)
 for a,b in zip(o.data.uv_layers,p.data.uv_layers):
  assert len(a.data)==len(b.data);assert max((x.uv-y.uv).length for x,y in zip(a.data,b.data))<1e-7
 assert not any(str(x.get('program_key','')).startswith(row['key']+'_') for x in bpy.context.scene.objects)
 rows.append(dict(key=row['key'],native_coordinate_error_m=err,topology_uv_material_indices_match=True,scale=list(o.scale)))
w=bpy.context.scene.world;out=next(n for n in w.node_tree.nodes if n.type=='OUTPUT_WORLD' and n.is_active_output);seen=set();stack=[out];env=[]
while stack:
 n=stack.pop()
 if n in seen:continue
 seen.add(n)
 if n.type=='TEX_ENVIRONMENT':env.append(n)
 stack.extend(link.from_node for s in n.inputs for link in s.links)
assert len(env)==1 and env[0].image and env[0].image.packed_file
report={'pass':True,'candidate_sha256':m['candidate_sha256'],'chairs':rows,'active_world_packed_environment_sha256':hashlib.sha256(env[0].image.packed_file.data).hexdigest(),'scope':'Native coordinates up to rigid centering, topology, material indices, UVs, unit scale and legacy auxiliary absence. Active packed HDR connected to world output. No shader equivalence, navigation or visual acceptance.'}
(d/'taskchairs112_saved_audit.json').write_text(json.dumps(report,indent=2));print('OFFICE112_SAVED_AUDIT_PASS')
