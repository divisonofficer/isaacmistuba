"""Read-only measured structure on plan's private6/conference shared boundary."""
import bpy,json,hashlib,sys,argparse
import numpy as np
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree
parser=argparse.ArgumentParser();parser.add_argument('--revision',type=int,default=92);parser.add_argument('--out',type=Path);args=parser.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else []);rev=args.revision
R=Path(__file__).resolve().parents[3];D=R/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';S=R/f'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full/scene_candidate_r{rev}.blend';O=args.out or D/f'private_conference_partition_probe_r{rev}.json';assert not O.exists();bpy.ops.wm.open_mainfile(filepath=str(S));dg=bpy.context.evaluated_depsgraph_get();trees={};objects=[]
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
for x in [.9,1.5,2.5,3.5,4.15,4.35,4.8,5.25,5.5]:
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
doors=[]
for o in bpy.context.scene.objects:
 if o.type!='MESH' or 'DoorFactory' not in o.name:continue
 h=hashlib.sha256()
 for collection,field,count,dtype in [(o.data.vertices,'co',len(o.data.vertices)*3,np.float32),(o.data.loops,'vertex_index',len(o.data.loops),np.int32),(o.data.polygons,'loop_total',len(o.data.polygons),np.int32),(o.data.polygons,'material_index',len(o.data.polygons),np.int32)]:
  a=np.empty(count,dtype=dtype);collection.foreach_get(field,a);h.update(a.tobytes())
 doors.append({'object':o.name,'raw_geometry_sha256':h.hexdigest(),'matrix_world':[list(v) for v in o.matrix_world],'materials':[m.name if m else None for m in o.data.materials]})
contracts={}
for obj in objects:
 for name in obj['materials']:
  if not name or name in contracts:continue
  m=bpy.data.materials[name];bs=next((n for n in m.node_tree.nodes if n.type=='BSDF_PRINCIPLED'),None) if m.use_nodes else None
  if bs:contracts[name]={'transmission':bs.inputs['Transmission Weight'].default_value,'transmission_linked':bs.inputs['Transmission Weight'].is_linked,'alpha':bs.inputs['Alpha'].default_value,'alpha_linked':bs.inputs['Alpha'].is_linked}

O.write_text(json.dumps({'source':str(S),'source_sha256':hashlib.sha256(S.read_bytes()).hexdigest(),'plan_reference':'floorplan_reference_v3.png','authored_room_mapping':{'private6':'office_0/5','conference_a':'office_0/6','shared_plane_y':18,'private_shared_x_interval':[.81,4]},'structural_objects':objects,'door_geometry_poses':doors,'material_contracts':contracts,'bidirectional_rays':rows,'scope':'Named structural walls/exteriors/glazing nearY18 only,18sample locations each both directions. Material names recorded,not full shader-opacity/visibility/volume or all scene object certification. Room labels derive authored mapping,not unreadable plan labels.','no_scene_modified':True},indent=2)+'\n');print('PRIVATE_CONFERENCE_PARTITION_PROBE_COMPLETE',len(objects),len(rows),flush=True)
