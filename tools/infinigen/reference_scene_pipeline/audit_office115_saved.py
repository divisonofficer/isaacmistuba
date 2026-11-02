"""Reopen finish-only candidate: raw geometry, poses, old UV charts, untargeted bindings."""
import bpy,json,sys,hashlib,array
from pathlib import Path
r=Path(__file__).resolve().parents[3];sys.path.insert(0,str(Path(__file__).parent));from compact_wc_contract import mesh_geometry_hash
D=r/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';a=json.loads((D/'wood115_build.json').read_text());targets={x['object']:x for x in a['rows']}
def digestuv(layer):
 x=array.array('f',[0])*(2*len(layer.data));layer.data.foreach_get('uv',x);return hashlib.sha256(x.tobytes()).hexdigest()
bpy.ops.wm.open_mainfile(filepath=a['source']);bpy.context.view_layer.update();before={}
for o in bpy.context.scene.objects:
 before[o.name]={'matrix':[list(v) for v in o.matrix_world],'geometry':mesh_geometry_hash(o.data) if o.type=='MESH' else None,'slots':[m.name if m else None for m in o.data.materials] if o.type=='MESH' else [],'uv':{l.name:digestuv(l) for l in o.data.uv_layers} if o.type=='MESH' else {}}
bpy.ops.wm.open_mainfile(filepath=a['candidate']);bpy.context.view_layer.update();failures=[]
assert set(before)=={o.name for o in bpy.context.scene.objects}
for o in bpy.context.scene.objects:
 b=before[o.name]
 if b['matrix']!=[list(v) for v in o.matrix_world]:failures.append([o.name,'matrix'])
 if o.type!='MESH':continue
 if b['geometry']!=mesh_geometry_hash(o.data):failures.append([o.name,'geometry'])
 for name,h in b['uv'].items():
  if name not in o.data.uv_layers or digestuv(o.data.uv_layers[name])!=h:failures.append([o.name,'original_uv',name])
 expected=b['slots'].copy()
 if o.name in targets:
  for k in targets[o.name]['replaced_slots']:expected[int(k)]='Office115_photographic_oak_metres'
  assert o.data.uv_layers.get('Office115_oak_metres')
 if expected!=[m.name if m else None for m in o.data.materials]:failures.append([o.name,'material_bindings'])
result={'source':a['source'],'candidate':a['candidate'],'objects_checked':len(before),'target_objects':len(targets),'failures':failures,'bounded_pass':not failures,'accepted':False,'scope':'Reopened source and115 raw topology/vertices,object matrices,all original UV float bytes,only intended24 object material slots changed,new metric chart exists. Does not compare all modifier/shader/light internals or certify rendering/physical manufacture/photorealism.'};(D/'wood115_saved_audit.json').write_text(json.dumps(result,indent=2));print('OFFICE115_REOPENED',result['bounded_pass'],failures[:10],flush=True)
