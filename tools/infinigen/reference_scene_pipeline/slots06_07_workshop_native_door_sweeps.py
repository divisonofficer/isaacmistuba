"""Read-only current scene native moving-leaf/lever triangles at37poses perdoor."""
import bpy,json,sys,math
from pathlib import Path
from mathutils import Vector,Matrix
from mathutils.bvhtree import BVHTree
R=Path(__file__).resolve().parents[3];W=R/'out/infinigen_v2/kr_industrial_workshop_floor_06_48712506';src=max(W.glob('furnished_*.blend'),key=lambda p:p.stat().st_mtime);rev=src.stem.removeprefix('furnished_');bpy.ops.wm.open_mainfile(filepath=str(src));inv=json.loads((W/f'native_product_inventory_{rev}.json').read_text());docs=[json.loads((W/f).read_text())for f in['workshop_measured_entry_r3.json']];doorrows=[r for d in docs for r in d['native_doors']];obstacles=[bpy.data.objects[n]for p in inv['products']for n in p['objects']];obstacles +=[o for o in bpy.data.objects if o.type=='MESH'and(o.name.endswith(('.wall','.exterior'))or'WC_route_corrected_partition'in o.name or'North_WC_source_program_partition'in o.name or o.name.startswith('Workshop_native_measured_')or'DoorCasingFactory'in o.name)];cache={};records=[]
def bounds(ps):return Vector([min(p[k]for p in ps)for k in range(3)]),Vector([max(p[k]for p in ps)for k in range(3)])
def tree(o):
 if o.name not in cache:
  o.data.calc_loop_triangles();ps=[o.matrix_world@v.co for v in o.data.vertices];cache[o.name]=BVHTree.FromPolygons(ps,[list(t.vertices)for t in o.data.loop_triangles],all_triangles=True)
 return cache[o.name]
for row in doorrows:
 o=bpy.data.objects[row['new_object']];o.data.calc_loop_triangles();used={i for p in o.data.polygons for i in p.vertices};attr=o.data.attributes['door_left'];moving=[i for i in used if attr.data[i].value];mset=set(moving);tris=[list(t.vertices)for t in o.data.loop_triangles if all(i in mset for i in t.vertices)];current=[o.matrix_world@v.co for v in o.data.vertices];hinge=Vector(row['hinge_world_m']);angle=row['open_degrees'];inverse=Matrix.Rotation(-math.radians(angle),4,'Z');closed={i:hinge+inverse@(current[i]-hinge)for i in moving};hits=[]
 for step in range(37):
  deg=angle*step/36;rot=Matrix.Rotation(math.radians(deg),4,'Z');ps=current.copy()
  for i,p in closed.items():ps[i]=hinge+rot@(p-hinge)
  lo,hi=bounds([ps[i]for i in moving]);bt=BVHTree.FromPolygons(ps,tris,all_triangles=True)
  for other in obstacles:
   if other==o:continue
   bb=[other.matrix_world@Vector(v)for v in other.bound_box];q0,q1=bounds(bb)
   if not all(min(hi[k],q1[k])-max(lo[k],q0[k])>1e-5 for k in range(3)):continue
   n=len(bt.overlap(tree(other)))
   if n:hits.append({'degrees':deg,'obstacle':other.name,'actual_triangle_pairs':n,'intentional_own_casing_contact_candidate':other.name==row['kept_original_casing']})
 records.append({'door':o.name,'hinge_world_m':list(hinge),'open_degrees':angle,'actual_moving_faced_vertices':len(moving),'actual_moving_triangles':len(tris),'sampled_pose_count':37,'actual_triangle_hits':hits,'pass':not hits})
doc={'source':str(src),'rows':records,'pass_sampled_sweeps':all(r['pass']for r in records),'method':'Actual calc_loop_triangles on moving leaf+lever and nearby furniture/walls/exteriorSkins/otherdoors/casings. Fixed own native frame/hinge excluded;37rigidpose samples includingclosed/finalpose. No source geometry edited.','limitations':['Sampled surface intersections,not continuous contained-solid proof','Incidental touching triangles may require interpretation;hitsnever silentlyignored','No final wholephoto/accessibility approval'],'photorealism_accepted':False};(W/f'actual_all_native_door_sweeps_{rev}.json').write_text(json.dumps(doc,indent=2));print('ALL_NATIVE_DOOR_SWEEPS',doc['pass_sampled_sweeps'],[(r['door'],len(r['actual_triangle_hits']))for r in records],flush=True)
