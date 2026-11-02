import bpy,json,hashlib
from pathlib import Path
from mathutils import Vector
root=Path(__file__).resolve().parents[3];src=root/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full/scene_candidate_r77.blend';ref=root/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';bpy.ops.wm.open_mainfile(filepath=str(src));bpy.context.view_layer.update();lights=[];surfaces=[]
for o in bpy.context.scene.objects:
 key=o.get('program_key','');pos=o.matrix_world.translation
 if o.type=='LIGHT' and -.5<pos.x<9 and 5.5<pos.y<10:
  lights.append({'name':o.name,'key':key,'type':o.data.type,'energy':o.data.energy,'color':list(o.data.color),'position':list(pos),'rotation':list(o.rotation_euler),'size':getattr(o.data,'size',None),'parent':o.parent.name if o.parent else None,'hide_render':o.hide_render})
 if key.startswith('101_living') or o.name in ['living-room_0/0.wall','living-room_0/0.ceiling']:
  mats=[]
  for mat in o.data.materials if o.type=='MESH' else []:
   if not mat:continue
   nodes=[]
   for n in mat.node_tree.nodes if mat.use_nodes else []:
    if n.type=='BSDF_PRINCIPLED':nodes.append({'name':n.name,'type':n.type,'values':{i.name:list(i.default_value) if hasattr(i.default_value,'__len__') else i.default_value for i in n.inputs if i.name in ['Base Color','Emission Color','Emission Strength','Roughness']},'links':[(i.name,i.links[0].from_node.name) for i in n.inputs if i.is_linked]})
   mats.append({'name':mat.name,'principled':nodes})
  surfaces.append({'name':o.name,'key':key,'materials':mats,'bounds':[[min((o.matrix_world@Vector(v))[k] for v in o.bound_box) for k in range(3)],[max((o.matrix_world@Vector(v))[k] for v in o.bound_box) for k in range(3)]]})
w=bpy.context.scene.world;world={'name':w.name,'nodes':[{'name':n.name,'type':n.type,'links':[(i.name,i.links[0].from_node.name) for i in n.inputs if i.is_linked],'strength':n.inputs['Strength'].default_value if n.type=='BACKGROUND' else None} for n in w.node_tree.nodes]};(ref/'living_lighting_source_r77_probe.json').write_text(json.dumps({'source':str(src),'source_sha256':hashlib.sha256(src.read_bytes()).hexdigest(),'lights':lights,'surfaces':surfaces,'world':world,'scope':'Actual saved101 living light/fixture/material state only;no visual acceptance.'},indent=2)+'\n');print('LIVING_LIGHTING_SOURCE_PROBE_COMPLETE',len(lights),flush=True)
