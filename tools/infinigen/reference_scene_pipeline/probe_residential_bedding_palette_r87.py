import bpy,json
from pathlib import Path
r=Path(__file__).resolve().parents[3];d=r/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';s=r/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full/scene_candidate_r87.blend'
bpy.ops.wm.open_mainfile(filepath=str(s));rows=[]
for o in bpy.data.objects:
 k=o.get('program_key','')
 if o.type!='MESH' or not any(k.startswith(f'{u}_{room}_bed') for u in [101,102] for room in ['master','bedroom2','bedroom3']):continue
 mats=[]
 for m in o.data.materials:
  if not m:continue
  nodes=[]
  for n in m.node_tree.nodes if m.use_nodes else []:
   if n.type=='BSDF_PRINCIPLED':nodes.append({'node':n.name,'base':list(n.inputs['Base Color'].default_value),'base_linked':n.inputs['Base Color'].is_linked,'base_links':[(l.from_node.name,l.from_socket.name) for l in n.inputs['Base Color'].links]})
  mats.append({'name':m.name,'faces':sum(p.material_index==list(o.data.materials).index(m) for p in o.data.polygons),'principled':nodes})
 rows.append({'object':o.name,'program_key':k,'materials':mats})
(d/'bedding_palette_inventory_r87.json').write_text(json.dumps({'source':str(s),'scope':'Selected tagged bedroom bed/duvet mesh material roots; no colour correction or visibility acceptance.','objects':rows},indent=2));print('BEDDING_PALETTE_INVENTORY_COMPLETE')
