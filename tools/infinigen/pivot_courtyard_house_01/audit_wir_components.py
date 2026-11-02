import bpy,bmesh,json
from pathlib import Path
R=Path(__file__).resolve().parents[3];o=next(o for o in bpy.data.objects if o.name.startswith('OpenWardrobeFactory'));bm=bmesh.new();bm.from_mesh(o.data);seen=set();rows=[]
for v in bm.verts:
 if v in seen:continue
 seen.add(v);todo=[v];comp=[]
 while todo:
  p=todo.pop();comp.append(p)
  for e in p.link_edges:
   q=e.other_vert(p)
   if q not in seen:seen.add(q);todo.append(q)
 lo=[min(v.co[k] for v in comp) for k in range(3)];hi=[max(v.co[k] for v in comp) for k in range(3)];slots={f.material_index for v in comp for f in v.link_faces}
 rows.append({'lo':lo,'hi':hi,'slots':list(slots),'vertices':len(comp)})
bm.free();d={'object':o.name,'scale':list(o.scale),'components':rows};p=R/'data/venue_refs/floor_plans_v3/pivot_courtyard_house_01/wir_component_audit.json';p.write_text(json.dumps(d,indent=2));print('WIR_COMPONENT_AUDIT_COMPLETE',flush=True)
