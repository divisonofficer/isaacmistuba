import bpy,json,hashlib
from pathlib import Path
r=Path('/jarvis/project/robomituba');ref=r/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';src=r/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full/scene_candidate_r63.blend';bpy.ops.wm.open_mainfile(filepath=str(src));bpy.context.view_layer.update();deps=bpy.context.evaluated_depsgraph_get();parts=json.loads((ref/'kitchen_components_probe_r60.json').read_text());rows=[]
for parent in bpy.data.objects:
 if parent.type!='MESH' or 'HomeKitchenRunFactory' not in parent.name or not str(parent.get('program_key','')).endswith('_kitchen_run'):continue
 record=next(x for x in parts if x['key']==parent['program_key']);boxes=[p['local_bounds'] for p in record['parts'] if p['materials']==['ir_kit_top']];assert len(boxes)==4;child=next(x for x in bpy.data.objects if x.parent==parent and x.name.startswith('FormedSink_'));ev=child.evaluated_get(deps);me=ev.to_mesh();inside=[]
 for v in me.vertices:
  p=v.co
  for lo,hi in boxes:
   depths=[min(p[k]-lo[k],hi[k]-p[k]) for k in range(3)]
   if min(depths)>.00001:inside.append({'vertex':v.index,'local':list(p),'minimum_inside_depth_m':min(depths)});break
 ev.to_mesh_clear();rows.append({'kitchen':parent.name,'evaluated_shell_vertices_inside_unchanged_counter_boxes':len(inside),'max_minimum_inside_depth_m':max((x['minimum_inside_depth_m'] for x in inside),default=0),'examples':inside[:8]})
d={'source':str(src),'source_sha256':hashlib.sha256(src.read_bytes()).hexdigest(),'records':rows,'scope':'Evaluated new bowl vertices strictly inside current unchanged counter primitive volumes. Detects actual finite overlap,not boundary contact;does not exhaust triangle/triangle collision or plumbing.','photorealism_accepted':False};(ref/'formed_sink_fit_audit_r63.json').write_text(json.dumps(d,indent=2));print(json.dumps(rows),flush=True)
