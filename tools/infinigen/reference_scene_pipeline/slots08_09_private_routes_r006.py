"""Independent native-bedroom access andactual swept-mesh private routes.
Source-native adult products keep unit size. Only actual partitions/placement change.
"""
import bpy,bmesh,json,sys,os,traceback,hashlib,math
from pathlib import Path
from mathutils import Vector,Matrix
from mathutils.bvhtree import BVHTree
R=Path(__file__).resolve().parents[3];T=Path(__file__).parent;sys.path.insert(0,str(T));from physical_scene_geometry import render_mesh_candidates,evaluated_surface
D=R/'data/venue_refs/floor_plans_v3/skyline_penthouse_08';B=R/'out/infinigen_v2/kr_skyline_penthouse_08_48712508/full';src=B/'scene_candidate_r005.blend';out=B/'scene_candidate_r006.blend';assert not out.exists();job={'pid':os.getpid(),'phase':'independent_private_corridors','source':str(src),'device':'CPU'};jp=D/'build_r006_job.json';jp.write_text(json.dumps(job,indent=2))
def bounds(o):
 pts=[o.matrix_world@Vector(v)for v in o.bound_box];return Vector([min(v[k]for v in pts)for k in range(3)]),Vector([max(v[k]for v in pts)for k in range(3)])
def box(name,loc,dims,mat):
 bpy.ops.mesh.primitive_cube_add(size=1,location=loc);o=bpy.context.object;o.name=name;o.dimensions=dims;bpy.ops.object.transform_apply(location=False,rotation=False,scale=True);o.data.materials.append(mat);m=o.modifiers.new('Construction arris','BEVEL');m.width=.006;m.segments=3;return o

def shift(prefix,delta):
 for o in bpy.context.scene.objects:
  if o.name.startswith(prefix):o.location+=Vector(delta)

def routes():
 obs,inventory=render_mesh_candidates();obs +=[o for o in bpy.context.scene.objects if o.type=='CURVE'and not o.hide_render];results=[];low=.13;high=1.88;radius=.302
 definitions=[('hall_to_bedroom2',[(11.42,6.5),(11.42,1.55),(12.7,1.55)]),('hall_to_bedroom3',[(16.425,6.5),(16.425,1.55),(18,1.55)]),('hall_dressing_masterbath',[(7.05,6.5),(7.05,4.3),(6.95,3.2),(7.05,2.6),(7.25,1.75)])]
 def hull(points):
  pts=sorted(set(points))
  def cross(o,a,b):return(a[0]-o[0])*(b[1]-o[1])-(a[1]-o[1])*(b[0]-o[0])
  lower=[]
  for p in pts:
   while len(lower)>=2 and cross(lower[-2],lower[-1],p)<=0:lower.pop()
   lower.append(p)
  upper=[]
  for p in reversed(pts):
   while len(upper)>=2 and cross(upper[-2],upper[-1],p)<=0:upper.pop()
   upper.append(p)
  return lower[:-1]+upper[:-1]
 def distance(p,a,b):
  dx=b[0]-a[0];dy=b[1]-a[1];t=max(0,min(1,((p.x-a[0])*dx+(p.y-a[1])*dy)/(dx*dx+dy*dy)));return math.hypot(p.x-a[0]-t*dx,p.y-a[1]-t*dy)
 for name,points in definitions:
  segments=[];all_collisions=[]
  for a,b in zip(points,points[1:]):
   boundary=hull([(p[0]+radius*math.cos(i*math.tau/64),p[1]+radius*math.sin(i*math.tau/64))for p in[a,b]for i in range(64)]);n=len(boundary);verts=[Vector((x,y,z))for z in[low,high]for x,y in boundary];faces=[]
   for i in range(1,n-1):faces.extend([(0,i,i+1),(n,n+i+1,n+i)])
   for i in range(n):k=(i+1)%n;faces.append((i,k,n+k,n+i))
   tree=BVHTree.FromPolygons(verts,faces);x0=min(a[0],b[0])-radius;x1=max(a[0],b[0])+radius;y0=min(a[1],b[1])-radius;y1=max(a[1],b[1])+radius;collisions=[];tested=[]
   for o in obs:
    lo,hi=bounds(o)
    if hi.x<x0 or lo.x>x1 or hi.y<y0 or lo.y>y1 or hi.z<low or lo.z>high:continue
    ps,fs,used=evaluated_surface(o);ot=BVHTree.FromPolygons(ps,fs,all_triangles=True);cross=tree.overlap(ot);inside=sum(1 for i in used if low+1e-5<ps[i].z<high-1e-5 and distance(ps[i],a,b)<radius);row={'object':o.name,'surface_crossings':len(cross),'physical_vertices_inside_route':inside};tested.append(row)
    if cross or inside:collisions.append(row)
   segments.append({'from_xy_m':a,'to_xy_m':b,'tested':tested,'collisions':collisions});all_collisions.extend(collisions)
  results.append({'route':name,'points_xy_m':points,'minimum_width_m':.6,'conservative_capsule_radius_m':radius,'z_bounds_m':[low,high],'all_candidate_render_meshes_and_curves':True,'segments':segments,'collisions':all_collisions,'clear_in_tested_scope':not all_collisions})
 return results,inventory

try:
 bpy.ops.wm.open_mainfile(filepath=str(src));changes=[]
 # Separate narrow branch corridors from family andbedroom2; preserve original bed/door product sizes.
 for o in bpy.context.scene.objects:
  if o.type!='MESH'or not o.name.endswith(('.wall','.exterior')):continue
  bm=bmesh.new();bm.from_mesh(o.data);bm.transform(o.matrix_world)
  for x in[10.85,12,15.85,17]:bmesh.ops.bisect_plane(bm,geom=list(bm.verts)+list(bm.edges)+list(bm.faces),dist=.000001,plane_co=Vector((x,0,0)),plane_no=Vector((1,0,0)))
  delete=[]
  for f in bm.faces:
   c=f.calc_center_median()
   if abs(f.normal.y)<.5:continue
   corridor2=10.85<c.x<12.01 and 5.1<c.y<5.9
   corridor3=15.85<c.x<17.01 and(3.1<c.y<3.9 or 5.1<c.y<5.9)
   if corridor2 or corridor3:delete.append(f)
  if delete:bmesh.ops.delete(bm,geom=delete,context='FACES');changes.append({'object':o.name,'opened_partition_faces':len(delete)})
  bm.transform(o.matrix_world.inverted());bm.to_mesh(o.data);bm.free()
 wall=bpy.data.materials['Warm lime plaster']
 for x,name in[(10.85,'Family_east_branch_private_hall'),(15.85,'Bedroom2_east_branch_private_hall')]:box(name,(x,2.75,1.71),(.18,5.5,3.2),wall)
 shift('family_sofa_',(-.3,0,0));shift('bathroom_0_adult_toilet',(-.15,-.9,0));shift('bathroom_0_pedestal_basin',(.2,-.5,0));shift('bathroom_1_adult_toilet',(-1.5,0,0));shift('bathroom_1_pedestal_basin',(-.5,0,0))
 # Original generator used obstructing paired-leaf meshes; install actual native950mm single-leaf assemblies.
 door_asset=R/'data/venue_refs/floor_plans_v3/commercial_office_floor_02/native_flat_door_pilot02/asset.blend';door_rows=[]
 openings=[('bedroom2','LiteDoorFactory(1201675).spawn_asset(8)','DoorCasingFactory(1201675).spawn_asset(8)',12,1.55,True,-90,'min'),('bedroom3','LouverDoorFactory(2557303).spawn_asset(10)','DoorCasingFactory(2557303).spawn_asset(10)',17,1.55,True,-90,'min'),('dressing','LouverDoorFactory(2557303).spawn_asset(4)','DoorCasingFactory(2557303).spawn_asset(4)',7.05,5.5,False,90,'max'),('master_bath','LiteDoorFactory(1201675).spawn_asset(7)','DoorCasingFactory(1201675).spawn_asset(7)',6.95,3.2,False,-90,'min')]
 rects=[(10.85,5.1,12.01,5.9),(15.85,5.1,17.01,5.9),(15.85,3.1,17.01,3.9)]
 for key,leaf,casing,x,y,vertical,angle,side in openings:rects.append((x-.4,y-.6,x+.4,y+.6)if vertical else(x-.6,y-.4,x+.6,y+.4))
 # Cut actual rough openings in native walls/exteriors;then trim source plinth across everynew opening.
 for o in list(bpy.context.scene.objects):
  is_plinth=o.name.startswith('skirtingboard_support');is_wall=o.type=='MESH'and o.name.endswith(('.wall','.exterior'))
  if not(is_plinth or is_wall):continue
  if is_plinth and o.type!='MESH':
   bpy.ops.object.select_all(action='DESELECT');o.select_set(True);bpy.context.view_layer.objects.active=o;bpy.ops.object.convert(target='MESH');o=bpy.context.object
  bm=bmesh.new();bm.from_mesh(o.data);bm.transform(o.matrix_world)
  for x in sorted({r[k]for r in rects for k in[0,2]}):bmesh.ops.bisect_plane(bm,geom=list(bm.verts)+list(bm.edges)+list(bm.faces),dist=.000001,plane_co=Vector((x,0,0)),plane_no=Vector((1,0,0)))
  for y in sorted({r[k]for r in rects for k in[1,3]}):bmesh.ops.bisect_plane(bm,geom=list(bm.verts)+list(bm.edges)+list(bm.faces),dist=.000001,plane_co=Vector((0,y,0)),plane_no=Vector((0,1,0)))
  delete=[]
  for f in bm.faces:
   c=f.calc_center_median()
   if is_wall and abs(f.normal.z)>.5:continue
   if is_plinth and c.z>.5:continue
   if any(x0<c.x<x1 and y0<c.y<y1 for x0,y0,x1,y1 in rects):delete.append(f)
  if delete:bmesh.ops.delete(bm,geom=delete,context='FACES')
  bm.transform(o.matrix_world.inverted());bm.to_mesh(o.data);bm.free()
 for key,oldleaf,oldcasing,x,y,vertical,angle,side in openings:
  for name in[oldleaf,oldcasing]:
   obj=bpy.data.objects.get(name)
   if obj:bpy.data.objects.remove(obj,do_unlink=True)
  with bpy.data.libraries.load(str(door_asset),link=False)as(a,b):b.objects=['Office02_native_flat_leaf_full_frame_lever']
  o=b.objects[0];bpy.context.scene.collection.objects.link(o);bpy.context.view_layer.update();o.parent=None;o.matrix_world=Matrix.Translation(Vector((x,y,.11)))@Matrix.Rotation(math.pi/2 if vertical else 0,4,'Z');o.name='Native950mm_private_'+key
  used={i for f in o.data.polygons for i in f.vertices};frame=[i for i in used if o.data.attributes['door_frame'].data[i].value];moving=[i for i in used if o.data.attributes['door_left'].data[i].value];leaf=[i for i in used if o.data.attributes['door'].data[i].value];assert frame and moving and leaf
  ps=[o.matrix_world@o.data.vertices[i].co for i in leaf];lo=Vector([min(v[k]for v in ps)for k in range(3)]);hi=Vector([max(v[k]for v in ps)for k in range(3)]);native_dims=list(hi-lo);pivot=Vector((x,lo.y,0))if vertical else Vector((hi.x if side=='max'else lo.x,y,0));inv=o.matrix_world.inverted();rot=Matrix.Rotation(math.radians(angle),4,'Z');dz=.118-lo.z
  for i in moving:p=o.matrix_world@o.data.vertices[i].co;o.data.vertices[i].co=inv@(pivot+rot@(p+Vector((0,0,dz))-pivot))
  embedded=0
  for i in frame:
   p=o.matrix_world@o.data.vertices[i].co
   if p.z<.17:p.z-=.08;o.data.vertices[i].co=inv@p;embedded+=1
  o.data.update();o['native_source_factory']='BaseDoorFactory';o['native_leaf_requested_width_m']=.95;o['native_leaf_requested_height_m']=2.3;o['post_generation_rescaling']=False;o['native_leaf_open_angle_deg']=angle
  # Actual rough reveal fillers and header complete remaining3.09m native wall opening.
  header_bottom=.11+2.37805;box('Door_header_'+key,(x,y,(header_bottom+3.09)/2),(.22,1.2,3.09-header_bottom)if vertical else(1.2,.22,3.09-header_bottom),wall)
  for sign in[-1,1]:box('Door_reveal_'+key+str(sign),(x,y+sign*.557)if False else((x,y+sign*.557,1.299)if vertical else(x+sign*.557,y,1.299)),(.22,.086,2.378)if vertical else(.086,.22,2.378),wall)
  door_rows.append({'door':key,'actual_source':str(door_asset),'source_leaf_world_dimensions_before_pose':native_dims,'native_width_height_m':[.95,2.3],'native_leaf_pose_angle_deg':angle,'native_leaf_floor_gap_m':.008,'fixed_lower_frame_vertices_embedded_80mm':embedded,'post_generation_rescaling':False})
 (D/'native_private_doors_r006.json').write_text(json.dumps(door_rows,indent=2))
 bpy.context.view_layer.update();rows,inventory=routes();report={'source':str(src),'proposed_candidate':str(out),'partition_changes':changes,'routes':rows,'all3_reserved_routes_clear_in_tested_scope':all(r['clear_in_tested_scope']for r in rows),'scope':'600mm buffered specific private routes swept floorZ+20mm to1.88m against actual evaluated render meshes/curves,notbbox alone. Includes source-native adult doors in current savedpose,notdynamicdoor swing certification. Trianglesurfacecrossings andenclosedphysicalvertices tested. Fullfloorwidthsupport,allrooms,accessibilitystandards andwhole-navigation notcertified.','accepted':False};(D/'private_actual_mesh_routes_r006.json').write_text(json.dumps(report,indent=2));(D/'private_actual_mesh_inventory_r006.json').write_text(json.dumps(inventory,indent=2));assert report['all3_reserved_routes_clear_in_tested_scope'],[(r['route'],r['collisions'])for r in rows]
 bpy.ops.wm.save_as_mainfile(filepath=str(out));(D/'views_r006.json').write_text((D/'views_r005.json').read_text());job.update(phase='saved_mesh_routes_verified_render_pending',candidate=str(out),exit_code=0)
except BaseException as e:job.update(phase='failed',error=repr(e),traceback=traceback.format_exc(),exit_code=1);raise
finally:jp.write_text(json.dumps(job,indent=2));print(job,flush=True)
