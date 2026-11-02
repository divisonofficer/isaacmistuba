import bpy,json
from pathlib import Path
from mathutils import Vector
r=Path(__file__).resolve().parents[3];d=r/'data/venue_refs/floor_plans_v3/commercial_office_floor_02/native_flat_door_pilot';bpy.ops.wm.open_mainfile(filepath=str(d/'asset.blend'));o=bpy.data.objects['Office02_native_flat_leaf_full_frame_lever'];dg=bpy.context.evaluated_depsgraph_get();e=o.evaluated_get(dg);m=e.to_mesh();rows=[]
def bounds(pts):
 return {'lo':[min(p[k] for p in pts) for k in range(3)],'hi':[max(p[k] for p in pts) for k in range(3)]} if pts else None
for i,mat in enumerate(m.materials):
 faces=[f for f in m.polygons if f.material_index==i];ids={v for f in faces for v in f.vertices};rows.append({'material':mat.name if mat else None,'faces':len(faces),'bounds':bounds([o.matrix_world@m.vertices[v].co for v in ids])})
used={v for f in m.polygons for v in f.vertices};unused=[v for v in m.vertices if v.index not in used];out={'evaluated_face_vertex_bounds':bounds([o.matrix_world@m.vertices[v].co for v in used]),'all_evaluated_vertex_bounds':bounds([o.matrix_world@v.co for v in m.vertices]),'unused_vertices':len(unused),'unused_bounds':bounds([o.matrix_world@v.co for v in unused]),'materials':rows,'source_object_bounds':bounds([o.matrix_world@Vector(v) for v in o.bound_box]),'scope':'Exact realized assembly and per-material vertex envelope;not installation/sweep or photorealism proof.'};e.to_mesh_clear();(d/'evaluated_envelope.json').write_text(json.dumps(out,indent=2));print(json.dumps(out),flush=True)
