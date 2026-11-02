import bpy,json
from pathlib import Path
r=Path('/jarvis/project/robomituba');bpy.ops.wm.open_mainfile(filepath=str(r/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full/scene_candidate_r62.blend'))
rows=[]
for o in bpy.data.objects:
 if o.name not in ['Office02_conference_a_display','Office02_meeting_b_display','Office02_meeting_c_display']:continue
 mats=[]
 for m in o.data.materials:
  if not m:continue
  mats.append({'name':m.name,'nodes':[{'name':n.name,'type':n.type,'inputs':{i.name:i.default_value if isinstance(i.default_value,(int,float,str)) else list(i.default_value) for i in n.inputs if hasattr(i,'default_value') and not i.is_linked}} for n in m.node_tree.nodes] if m.use_nodes else [],'links':[(l.from_node.name,l.from_socket.name,l.to_node.name,l.to_socket.name) for l in m.node_tree.links] if m.use_nodes else []})
 rows.append({'object':o.name,'key':o.get('program_key'),'materials':mats})
p=r/'data/venue_refs/floor_plans_v3/commercial_office_floor_02/presentation_screen_probe_r62.json';p.write_text(json.dumps(rows,indent=2));print(p,len(rows),flush=True)
