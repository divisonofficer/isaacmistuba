"""Inventory actual native frame attributes for static ground-floor route diagnosis."""
import bpy,json,sys,hashlib
from pathlib import Path
from mathutils import Vector
r=Path(__file__).resolve().parents[3];sys.path.insert(0,str(Path(__file__).parent));from physical_scene_geometry import render_mesh_candidates
src=r/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full/scene_candidate_r125_draft.blend';d=r/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';bpy.ops.wm.open_mainfile(filepath=str(src));objects,inventory=render_mesh_candidates();rows=[]
for o in objects:
 a=o.data.attributes.get('door_frame')
 if not a or a.domain!='POINT':continue
 ev=o.evaluated_get(bpy.context.evaluated_depsgraph_get());me=ev.to_mesh();attr=me.attributes.get('door_frame');pts=[ev.matrix_world@v.co for v,f in zip(me.vertices,attr.data) if f.value>.5];allpts=[ev.matrix_world@v.co for v in me.vertices];ev.to_mesh_clear()
 if not pts:continue
 lo=[min(p[k] for p in pts) for k in range(3)];hi=[max(p[k] for p in pts) for k in range(3)];axis=0 if hi[0]-lo[0]<hi[1]-lo[1] else 1;tangent=1-axis;centre=[(x+y)/2 for x,y in zip(lo,hi)];row={'object':o.name,'program_key':o.get('program_key'),'frame_bbox_m':[lo,hi],'frame_normal_axis':axis,'frame_tangent_axis':tangent,'frame_center_m':centre,'full_mesh_bbox_m':[[min(p[k] for p in allpts) for k in range(3)],[max(p[k] for p in allpts) for k in range(3)]],'attributes':[(a.name,a.domain,a.data_type) for a in o.data.attributes],'custom_properties':{k:str(v) for k,v in o.items()}};rows.append(row)
(d/'door_frames125_inventory.json').write_text(json.dumps({'source':str(src),'source_sha256':hashlib.sha256(src.read_bytes()).hexdigest(),'doors':rows,'scope':'Native saved frame attributes, current static door geometry; outer frame center is not proof of usable clear opening or sweep.'},indent=2));print('NATIVE125_DOOR_FRAMES',[(x['object'],x['frame_center_m'],x['frame_bbox_m']) for x in rows])
