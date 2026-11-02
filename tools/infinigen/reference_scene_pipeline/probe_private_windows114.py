import bpy,json
from pathlib import Path
from mathutils import Vector
r=Path(__file__).resolve().parents[3];d=r/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';src=r/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full/scene_candidate_r113_draft.blend';bpy.ops.wm.open_mainfile(filepath=str(src));mapping=json.loads((d/'room_mapping.json').read_text());rows=[]
for key,row in mapping.items():
 if not key.startswith('private_office_'):continue
 ys=[x[1] for x in row['polygon_m']];cy=(min(ys)+max(ys))/2;objects=[]
 for o in bpy.context.scene.objects:
  if o.type!='MESH' or 'WindowFactory' not in o.name:continue
  points=[o.matrix_world@v.co for v in o.data.vertices];lo=Vector([min(v[k] for v in points) for k in range(3)]);hi=Vector([max(v[k] for v in points) for k in range(3)])
  if hi.x>1.4 or not min(ys)<(lo.y+hi.y)/2<max(ys):continue
  glassids={i for i,m in enumerate(o.data.materials) if m and 'glass' in m.name.lower()};ids={i for f in o.data.polygons if f.material_index in glassids for i in f.vertices};gp=[o.matrix_world@o.data.vertices[i].co for i in ids];gc=(Vector([min(v[k] for v in gp) for k in range(3)])+Vector([max(v[k] for v in gp) for k in range(3)]))/2 if gp else None;objects.append({'object':o.name,'parent':o.parent.name if o.parent else None,'matrix':[list(v) for v in o.matrix_world],'glass_bounds_center':list(gc) if gc else None,'bounds':[list(lo),list(hi)],'children':[{'object':x.name,'type':x.type} for x in o.children_recursive]})
 wall=bpy.data.objects.get(row['room_id']+'.exterior');rows.append({'room':key,'room_id':row['room_id'],'polygon':row['polygon_m'],'wall_object':wall.name if wall else None,'windows':objects})
(d/'private_windows114_source_probe.json').write_text(json.dumps({'source':str(src),'rooms':rows,'scope':'Current actual west-window/glass centers and wall identifiers only; no aperture/fit acceptance.'},indent=2));print(json.dumps(rows,indent=2))
