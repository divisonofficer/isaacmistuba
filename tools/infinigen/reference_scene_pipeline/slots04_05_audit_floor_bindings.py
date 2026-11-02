"""Read-only saved-floor shader assignments/UV evidence. Never saves blend."""
import bpy,json,collections,statistics,math
from pathlib import Path
R=Path(__file__).resolve().parents[3]
def value(v):
 if isinstance(v,(str,int,float,bool)) or v is None:return v
 try:return list(v)
 except TypeError:return str(v)
def tree(t,seen=None):
 seen=set() if seen is None else seen
 if t.as_pointer() in seen:return {'name':t.name,'already_seen':True}
 seen.add(t.as_pointer());nodes=[]
 for n in t.nodes:
  row={'name':n.name,'type':n.bl_idname,'mute':n.mute,'node_attributes':{k:value(getattr(n,k)) for k in ['data_type','blend_type','offset','offset_frequency','squash','squash_frequency'] if hasattr(n,k)},'inputs_by_index':[{'index':i,'identifier':sock.identifier,'name':sock.name,'linked':sock.is_linked,'default':value(sock.default_value) if hasattr(sock,'default_value') else None} for i,sock in enumerate(n.inputs)],'inputs':{s.name:value(s.default_value) for s in n.inputs if hasattr(s,'default_value') and not s.is_linked}}
  if hasattr(n,'image') and n.image:row['image']={'name':n.image.name,'filepath':n.image.filepath,'packed':bool(n.image.packed_file),'size':list(n.image.size),'colorspace':n.image.colorspace_settings.name}
  for k in ['uv_map','vector_type','attribute_name','operation','interpolation','projection']:
   if hasattr(n,k):row[k]=value(getattr(n,k))
  if hasattr(n,'object') and n.object:row['coordinate_object']=n.object.name
  if n.type=='GROUP' and n.node_tree:row['group_tree']=tree(n.node_tree,seen)
  nodes.append(row)
 return {'name':t.name,'nodes':nodes,'links':[{'from_node':l.from_node.name,'from_socket':l.from_socket.name,'from_socket_identifier':l.from_socket.identifier,'to_node':l.to_node.name,'to_socket':l.to_socket.name,'to_socket_identifier':l.to_socket.identifier} for l in t.links]}
def active_ancestors(t):
 outputs=[n for n in t.nodes if n.type=='OUTPUT_MATERIAL' and n.is_active_output];seen=set();todo=list(outputs)
 while todo:
  n=todo.pop()
  if n.name in seen:continue
  seen.add(n.name)
  todo += [l.from_node for s in n.inputs for l in s.links]
 return sorted(seen)
for scene,seed,slot in [('rural_stone_cottage_04',48712504,'04'),('shared_dining_residence_05',48712505,'05')]:
 D=R/'data/venue_refs/floor_plans_v3'/scene;src=R/'out/infinigen_v2'/f'kr_{scene}_{seed}'/'full'/f'scene_candidate_slots{slot}_r5.blend';bpy.ops.wm.open_mainfile(filepath=str(src));bpy.context.view_layer.update();rows=[];materials={}
 for o in bpy.context.scene.objects:
  if o.type!='MESH' or not o.name.endswith('.floor'):continue
  pts=[o.matrix_world@v.co for v in o.data.vertices];bounds={'min':[min(v[k] for v in pts) for k in range(3)],'max':[max(v[k] for v in pts) for k in range(3)]};counts=collections.Counter(p.material_index for p in o.data.polygons);slots=[]
  for i,s in enumerate(o.material_slots):
   m=s.material;slots.append({'slot_index':i,'slot_link':s.link,'material':m.name if m else None,'assigned_polygon_count':counts.get(i,0)})
   if m and m.name not in materials:materials[m.name]={'use_nodes':m.use_nodes,'active_material_output_ancestors':active_ancestors(m.node_tree) if m.use_nodes else [],'node_tree':tree(m.node_tree) if m.use_nodes else None}
  uvrows=[]
  for uv in o.data.uv_layers:
   xy=[x.uv for x in uv.data];dens=[]
   for p in o.data.polygons:
    loops=list(p.loop_indices)
    for a,b in zip(loops,loops[1:]+loops[:1]):
     pa=o.matrix_world@o.data.vertices[o.data.loops[a].vertex_index].co;pb=o.matrix_world@o.data.vertices[o.data.loops[b].vertex_index].co;dist=(pb-pa).length
     if dist>1e-5:dens.append((uv.data[b].uv-uv.data[a].uv).length/dist)
   uvrows.append({'name':uv.name,'active':uv==o.data.uv_layers.active,'loop_count':len(xy),'min':[min(p[k] for p in xy) for k in range(2)] if xy else None,'max':[max(p[k] for p in xy) for k in range(2)] if xy else None,'edge_uv_units_per_world_m':{'min':min(dens),'median':statistics.median(dens),'max':max(dens)} if dens else None})
  deps=bpy.context.evaluated_depsgraph_get();ev=o.evaluated_get(deps);evaluated=ev.to_mesh(preserve_all_data_layers=True,depsgraph=deps);ecounts=collections.Counter(p.material_index for p in evaluated.polygons);eslots=[{'slot_index':i,'material':m.name if m else None,'assigned_polygon_count':ecounts.get(i,0)} for i,m in enumerate(evaluated.materials)]
  for m in evaluated.materials:
   if m and m.name not in materials:materials[m.name]={'use_nodes':m.use_nodes,'active_material_output_ancestors':active_ancestors(m.node_tree) if m.use_nodes else [],'node_tree':tree(m.node_tree) if m.use_nodes else None}
  erow={'vertices':len(evaluated.vertices),'polygons':len(evaluated.polygons),'material_slots':eslots,'polygon_material_index_histogram':dict(ecounts)};ev.to_mesh_clear();modifiers=[{'name':m.name,'type':m.type,'show_render':m.show_render,'show_viewport':m.show_viewport,'node_tree':tree(m.node_group) if m.type=='NODES' and m.node_group else None} for m in o.modifiers]
  rows.append({'object':o.name,'object_scale':list(o.scale),'matrix_world':[list(row) for row in o.matrix_world],'modifiers':modifiers,'evaluated_mesh':erow,'world_bounds_m':bounds,'vertices':len(o.data.vertices),'polygons':len(o.data.polygons),'material_slot_assignments':slots,'polygon_material_index_histogram':dict(counts),'invalid_slot_face_count':sum(n for i,n in counts.items() if i>=len(o.material_slots)),'uv_layers':uvrows})
 samples=[(4.2,7),(7.5,7),(9.2,10),(.4,8),(3,12),(11,6),(.8,3),(12,12)] if slot=='04' else [(8.4,6),(12,6),(12,9),(4,9),(4,7),(4,4),(6,2),(2.4,1.8)];hits=[]
 for x,y in samples:
  hit,loc,normal,index,obj,matrix=bpy.context.scene.ray_cast(bpy.context.evaluated_depsgraph_get(),(x,y,1.5),(0,0,-1),distance=2)
  row={'sample_xy_m':[x,y],'hit':hit}
  if hit:
   ev=obj.evaluated_get(bpy.context.evaluated_depsgraph_get());me=ev.to_mesh();pi=me.polygons[index].material_index if 0<=index<len(me.polygons) else None;mat=me.materials[pi].name if pi is not None and pi<len(me.materials) and me.materials[pi] else None;row.update(object=obj.name,hit_world_m=list(loc),polygon_index=index,material_index=pi,material=mat);ev.to_mesh_clear()
  hits.append(row)
 out={'visible_floor_surface_samples':hits,'source':str(src),'source_read_only':True,'floors':rows,'assigned_materials':materials,'scope':'Exact saved mesh slot assignments, active shader output ancestors, complete assigned material/group node links and UV/world density. UV density does not prove actual shader coordinates use UV; inspect links. No candidate saved, no material changes.'};(D/'candidate_r5_floor_visible_surface_audit.json').write_text(json.dumps(out,indent=2));print('FLOOR_BINDING_AUDIT_SAVED',scene,flush=True)
