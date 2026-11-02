"""Read-only independent wall-ray intersections for the actual black-pixel ray."""
import bpy,json,hashlib
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree
root=Path(__file__).resolve().parents[3];src=root/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full/scene_candidate_r84.blend';ref=root/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';before=hashlib.sha256(src.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(src));bpy.context.view_layer.update();dg=bpy.context.evaluated_depsgraph_get();origin=Vector((2.1,3.25,1.15));direction=Vector((.6075583,.7839553,-.1276204)).normalized();rows=[]
for o in bpy.context.scene.objects:
 if o.type!='MESH' or not (o.name.endswith('.wall') or o.name.endswith('.exterior')):continue
 for evaluated in [False,True]:
  ev=o.evaluated_get(dg) if evaluated else None;me=ev.to_mesh() if ev else o.data;verts=[o.matrix_world@v.co for v in me.vertices];tree=BVHTree.FromPolygons(verts,[list(p.vertices) for p in me.polygons]);hit,normal,face,distance=tree.ray_cast(origin,direction,20)
  if hit is not None and distance<5:
   poly=me.polygons[face];rows.append({'object':o.name,'evaluated':evaluated,'distance_m':distance,'point':list(hit),'face_normal_world':list(normal),'face_index':face,'face_material_index':poly.material_index,'face_vertices_world':[list(verts[i]) for i in poly.vertices],'materials':[s.material.name if s.material else None for s in o.material_slots],'hide_render':o.hide_render,'visible_camera':o.visible_camera,'raw_polygons':len(o.data.polygons),'evaluated_polygons':len(me.polygons)})
  if ev:ev.to_mesh_clear()
rows.sort(key=lambda x:x['distance_m']);assert rows;target=next(x for x in rows if x['object']=='office_0/0.exterior' and x['evaluated']);near=[x for x in rows if x['evaluated'] and abs(x['distance_m']-target['distance_m'])<.005];assert hashlib.sha256(src.read_bytes()).hexdigest()==before;out={'source':str(src),'source_sha256':before,'source_unchanged':True,'origin':list(origin),'direction':list(direction),'independent_wall_hits':rows,'evaluated_hits_within_5mm_of_actual_target':near,'scope':'Independent per-object ray intersections can reveal coincident walls missed by advance-epsilon scene ray casts. Raw/evaluated normals recorded. No geometry change or photographic acceptance.'};(ref/'private_black_wall_coincidence_r84.json').write_text(json.dumps(out,indent=2)+'\n');print('WALL_COINCIDENCE_PROBE_COMPLETE',len(rows),'near',len(near),flush=True)
