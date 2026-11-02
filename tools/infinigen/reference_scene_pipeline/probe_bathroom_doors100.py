import bpy,json,sys
from pathlib import Path
R=Path(__file__).resolve().parents[3];sys.path.insert(0,str(Path(__file__).parent));from wc_layout_checks import bounds,evaluated_geometry
D=R/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';O=D/'bathroom_door_inventory100.json';assert not O.exists();S=R/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full/scene_candidate_r97.blend';bpy.ops.wm.open_mainfile(filepath=str(S));rows=[]
for o in bpy.context.scene.objects:
 if o.type!='MESH':continue
 if not(o.data.attributes.get('door_frame') or 'door' in o.name.lower() or 'door' in str(o.get('program_key','')).lower()):continue
 ev,me,pts=evaluated_geometry(o);row={'object':o.name,'key':o.get('program_key',''),'bbox_m':[[min(p[k] for p in pts) for k in range(3)],[max(p[k] for p in pts) for k in range(3)]],'matrix':[list(v) for v in o.matrix_world],'attribute_counts':{}};a=me.attributes
 for name in ['door','door_frame','door_left','door_right','handle','axis_group']:
  at=a.get(name)
  if not at or at.domain!='POINT':continue
  ids=[i for i,v in enumerate(at.data) if v.value>.5];row['attribute_counts'][name]=len(ids)
  if ids:row[name+'_bbox_m']=[[min(pts[i][k] for i in ids) for k in range(3)],[max(pts[i][k] for i in ids) for k in range(3)]]
 for name in ['_posparent','_poschild','_axis']:
  at=a.get(name)
  if at and at.domain=='POINT':row[name]=list({tuple(round(x,6) for x in v.vector) for v in at.data})[:12]
 rows.append(row);ev.to_mesh_clear()
O.write_text(json.dumps(rows,indent=2))
