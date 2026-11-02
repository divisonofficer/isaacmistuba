"""Read-only measured structure on plan's private6/conference shared boundary."""
import bpy,json,hashlib
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree
R=Path(__file__).resolve().parents[3];D=R/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';S=R/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full/scene_candidate_r92.blend';O=D/'private_conference_partition_probe_r92.json';assert not O.exists();bpy.ops.wm.open_mainfile(filepath=str(S));dg=bpy.context.evaluated_depsgraph_get();trees={};objects=[]
visible=set()
def collect(layer,blocked=False):
 blocked=blocked or layer.exclude or layer.collection.hide_render
 if not blocked:visible.update(o.name for o in layer.collection.objects)
 for child in layer.children:collect(child,blocked)
collect(bpy.context.view_layer.layer_collection)
for o in bpy.context.scene.objects:
 if o.name not in visible:continue
 if o.type!='MESH' or o.hide_render or not (o.name.endswith(('.wall','.exterior')) or 'glaz' in o.name.lower()):continue
 bb=[o.matrix_world@Vector(v) for v in o.bound_box]
 if max(p.y for p in bb)<17.6 or min(p.y for p in bb)>18.4 or min(p.x for p in bb)>6 or max(p.x for p in bb)<.8:continue
 e=o.evaluated_get(dg);m=e.to_mesh();tree=BVHTree.FromPolygons([o.matrix_world@v.co for v in m.vertices],[list(f.vertices) for f in m.polygons]);indices=[f.material_index for f in m.polygons];materials=[mat.name if mat else None for mat in m.materials];trees[o.name]=(tree,indices,materials);objects.append({'name':o.name,'evaluated_faces':len(m.polygons),'materials':materials,'bounds_min':[min(p[k] for p in bb) for k in range(3)],'bounds_max':[max(p[k] for p in bb) for k in range(3)]});e.to_mesh_clear()
rows=[]
for x in [.9,1.5,2.5,3.5,4.15,5.5]:
 for z in [.5,1.4,2.4]:
  hits=[]
  for name,(tree,indices,materials) in trees.items():
   for y,dy in [(17.6,1),(18.4,-1)]:
    p,n,index,d=tree.ray_cast(Vector((x,y,z)),Vector((0,dy,0)),.8)
    if p is not None:
     mi=indices[index] if index is not None and 0<=index<len(indices) else None
     material=materials[mi] if mi is not None and 0<=mi<len(materials) else None
     hits.append({'object':name,'origin_y':y,'point':list(p),'normal':list(n),'polygon_index':index,'material_index':mi,'material':material,'material_binding_status':'assigned' if material else 'unassigned_or_unresolved','distance_m':d})
  rows.append({'x':x,'z':z,'hits':hits})
O.write_text(json.dumps({'source':str(S),'source_sha256':hashlib.sha256(S.read_bytes()).hexdigest(),'plan_reference':'floorplan_reference_v3.png','authored_room_mapping':{'private6':'office_0/5','conference_a':'office_0/6','shared_plane_y':18,'private_shared_x_interval':[.81,4]},'structural_objects':objects,'bidirectional_rays':rows,'scope':'Named structural walls/exteriors/glazing nearY18 only,18sample locations each both directions. Material names recorded,not full shader-opacity/visibility/volume or all scene object certification. Room labels derive authored mapping,not unreadable plan labels.','no_scene_modified':True},indent=2)+'\n');print('PRIVATE_CONFERENCE_PARTITION_PROBE_COMPLETE',len(objects),len(rows),flush=True)
