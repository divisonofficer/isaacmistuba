"""Single authorized metric-only native floor A/B, after preserved R5 completion."""
import bpy,json,hashlib
from pathlib import Path
R=Path(__file__).resolve().parents[3]
def plain(v):
 if isinstance(v,(str,int,float,bool)) or v is None:return v
 try:return list(v)
 except TypeError:return getattr(v,'name',str(v))
def compare_material_nodes(old,new):
 changes=[];assert set(old.node_tree.nodes.keys())==set(new.node_tree.nodes.keys())
 for a in old.node_tree.nodes:
  b=new.node_tree.nodes[a.name];assert a.bl_idname==b.bl_idname
  if hasattr(a,'image'):assert a.image==b.image
  for key in ['data_type','blend_type','operation','vector_type']:
   if hasattr(a,key):assert getattr(a,key)==getattr(b,key)
  for i,x in enumerate(a.inputs):
   if hasattr(x,'default_value'):
    av=plain(x.default_value);bv=plain(b.inputs[i].default_value)
    if av!=bv:changes.append({'node':a.name,'socket':x.name,'socket_index':i,'before':av,'after':bv})
 links=lambda m:sorted((l.from_node.name,l.from_socket.identifier,l.to_node.name,l.to_socket.identifier) for l in m.node_tree.links)
 assert links(old)==links(new);assert {(x['node'],x['socket']) for x in changes}=={('Brick Texture','Brick Width'),('Brick Texture','Row Height')};return changes
for scene,seed,slot in [('rural_stone_cottage_04',48712504,'04'),('shared_dining_residence_05',48712505,'05')]:
 D=R/'data/venue_refs/floor_plans_v3'/scene;assert json.loads((D/'candidate_r5_cpu/job.json').read_text()).get('exit_code')==0,'Preserve/finish existing R5 first'
 W=R/'out/infinigen_v2'/f'kr_{scene}_{seed}'/'full';src=W/f'scene_candidate_slots{slot}_r5.blend';out=W/f'scene_candidate_slots{slot}_r6_metric.blend';assert not out.exists();sha=hashlib.sha256(src.read_bytes()).hexdigest();receipt=json.loads((D/'candidate_r5_cpu/render/render_receipt.json').read_text());assert sha==receipt['source_sha256'];bpy.ops.wm.open_mainfile(filepath=str(src));mat=bpy.data.materials['shader_hardwood_floor'];new=mat.copy();new.name='shader_hardwood_floor_metric_r6';brick=new.node_tree.nodes['Brick Texture'];before={key:float(brick.inputs[key].default_value) for key in ['Brick Width','Row Height']};assert abs(before['Brick Width']-.8955067396)<1e-5 and abs(before['Row Height']-.0641979501)<1e-5
 brick.inputs['Brick Width'].default_value=1.5;brick.inputs['Row Height'].default_value=.18
 changed_sockets=compare_material_nodes(mat,new);rows=[]
 for o in bpy.context.scene.objects:
  if o.type=='MESH' and o.name.endswith('.floor'):
   count=0
   for i,s in enumerate(o.material_slots):
    if s.material==mat:s.material=new;count+=sum(p.material_index==i for p in o.data.polygons)
   if count:rows.append({'object':o.name,'face_count_assigned_to_copy':count,'original_material':mat.name,'new_material':new.name})
 assert len(rows)==(7 if slot=='04' else 2);bpy.ops.wm.save_as_mainfile(filepath=str(out));assert hashlib.sha256(src.read_bytes()).hexdigest()==sha
 views=json.loads((D/'candidate_r5_views.json').read_text())[:2]
 for v in views:v['name']=v['name'].replace('_r5','_r6_metric')
 (D/'candidate_r6_metric_views.json').write_text(json.dumps(views,indent=2));(D/'candidate_r6_metric_change.json').write_text(json.dumps({'source':str(src),'source_sha256':sha,'candidate':str(out),'changed_shader_sockets_verified':changed_sockets,'before_native_parameters':before,'after_native_parameters':{'Brick Width':1.5,'Row Height':.18},'estimated_world_joint_cell_m':{'before':[before['Brick Width'],before['Row Height']],'after':[1.5,.18]},'coordinate_evidence':'candidate_r5_floor_metric_diagnosis.json','face_bindings':rows,'fixed':'All other material nodes/values/colors/noise, all geometry, objects, UV/source texture data, lights/world/exposure/cameras/samples/resolution. Only two native Brick Texture float sockets differ on a material copy assigned to same existing face slots.','photorealism_accepted':False},indent=2));print('METRIC_ONLY_R6_SAVED',scene,flush=True)
