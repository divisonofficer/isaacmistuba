import bpy,json
from pathlib import Path
r=Path(__file__).resolve().parents[3];d=r/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';a=json.loads((d/'core116_route_obstruction_probe.json').read_text());bpy.ops.wm.open_mainfile(filepath=str(r/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full/scene_candidate_r116_draft.blend'));rows=[]
for row in a:
 o=bpy.data.objects[row['object']];pts=[]
 for q in row['inside_points'][:14]:
  idx=q['index'];attrs={}
  for key in ['axis_group','part_id','is_jointed','door_frame','door','door_left','door_right','handle']:
   attr=o.data.attributes.get(key)
   if attr and attr.domain=='POINT' and idx<len(attr.data):attrs[key]=getattr(attr.data[idx],'value',None)
  pts.append({'index':idx,'attrs':attrs})
 rows.append({'object':o.name,'points':pts,'visible_get':o.visible_get(),'hide_get':o.hide_get(),'hide_render':o.hide_render,'collections':[{'name':c.name,'hide_render':c.hide_render,'hide_viewport':c.hide_viewport} for c in o.users_collection]})
for name in ['door.010','door.021']:
 o=bpy.data.objects[name];rows.append({'object':name,'visible_get':o.visible_get(),'hide_get':o.hide_get(),'hide_render':o.hide_render,'collections':[{'name':c.name,'hide_render':c.hide_render,'hide_viewport':c.hide_viewport} for c in o.users_collection]})
(d/'core116_native_helpers_probe.json').write_text(json.dumps(rows,indent=2));print(json.dumps(rows))
