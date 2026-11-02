"""Geometric user design contract: native WC, bowl sides, full door sweep,0.6m route.
No building-code or hydraulic certification. Projected fixture bounds are conservative.
"""
import math,heapq
import bpy,numpy as np
from mathutils import Vector
from shapely.geometry import Polygon,Point,LineString,MultiPoint,box
from shapely.ops import unary_union
from shapely import affinity
from wc_layout_checks import bounds,evaluated_geometry,seat_measurement
DOORS={'101_ensuite':'LiteDoorFactory(7699791).spawn_asset(5)','101_bathroom1':'GlassPanelDoorFactory(1275309).spawn_asset(4)','101_bathroom2':'LiteDoorFactory(800570).spawn_asset(6)','101_laundry_wc':'LiteDoorFactory(7699791).spawn_asset(8)','102_ensuite':'LiteDoorFactory(7699791).spawn_asset(18)','102_bathroom1':'LiteDoorFactory(7699791).spawn_asset(17)','102_bathroom2':'LiteDoorFactory(7699791).spawn_asset(19)','102_laundry_wc':'LiteDoorFactory(7699791).spawn_asset(21)'}
WALL_INSET=.1160347

def xybox(o):
 lo,hi=bounds(o);return box(lo.x,lo.y,hi.x,hi.y)
def inner_room(program):
 p=Polygon(program['polygon_m']);return p.buffer(-WALL_INSET,join_style=2)
def polygons(shape):
 return [shape] if shape.geom_type=='Polygon' else [p for p in getattr(shape,'geoms',[]) if p.geom_type=='Polygon']
def seat_centre(o):
 meas=seat_measurement(o);ev,mesh,pts=evaluated_geometry(o);z=meas['floor_z']+meas['seat_height_m'];total=0.;center=Vector();forward_pts=[]
 for f in mesh.polygons:
  n=(ev.matrix_world.to_3x3().inverted().transposed()@f.normal).normalized();c=sum((pts[i] for i in f.vertices),Vector())/len(f.vertices)
  if n.z>.95 and abs(c.z-z)<.0015:
   ps=[pts[i] for i in f.vertices];a=sum((ps[j]-ps[0]).cross(ps[j+1]-ps[0]).length/2 for j in range(1,len(ps)-1));center+=c*a;total+=a;forward_pts.extend(ps)
 ev.to_mesh_clear();assert total>.01;return center/total,meas

def door_geometry(room_key,program):
 door=bpy.data.objects[DOORS[room_key]];ev,mesh,pts=evaluated_geometry(door);a=mesh.attributes;lo,hi=inner_room(program).bounds[0:2],inner_room(program).bounds[2:4];unit=int(room_key[:3]);wallx=max(p[0] for p in program['polygon_m']) if unit==101 else min(p[0] for p in program['polygon_m']);outside=1 if unit==101 else -1
 # Full-frame Lite doors retain a centred frame. Single-column Glass door was opened as a whole object;
 # its origin is the physical upper hinge at the inner jamb, independent of the displaced far column.
 frame=a.get('door_frame');ids=[i for i,v in enumerate(frame.data) if v.value>.5] if frame else []
 fpts=[pts[i] for i in ids];fl=[min(p[k] for p in fpts) for k in range(3)];fh=[max(p[k] for p in fpts) for k in range(3)];single='GlassPanelDoorFactory' in door.name
 if single:
  pivot=(float(door.matrix_world.translation.x),float(door.matrix_world.translation.y));width=.911587;low=pivot[1] if door.get('wc_access_hinge_jamb')=='lower' else pivot[1]-width;high=low+width;pivots=[pivot]
 else:
  low=fl[1]+.020;high=fh[1]-.020;normal_offset=(fh[0]-fl[0])/2;pivots=[(wallx+normal_offset,low),(wallx+normal_offset,high)]
 moving=[]
 for label in ['door_left','door_right']:
  at=a.get(label)
  if not at:continue
  indices=[];body=[]
  for i,v in enumerate(at.data):
   if v.value<=.5:continue
   is_body=a.get('door') and a['door'].data[i].value>.5;is_handle=a.get('handle') and a['handle'].data[i].value>.5;is_axis=a.get('axis_group') and a['axis_group'].data[i].value>.5
   if not is_axis and (is_body or is_handle):indices.append(i)
   if is_body and not is_axis:body.append(i)
  if not body:continue
  bodypts=np.array([(pts[i].x,pts[i].y) for i in body]);center=bodypts.mean(axis=0);_,axes=np.linalg.eigh(np.cov(bodypts.T));axis=axes[:,1]
  pivot=min(pivots,key=lambda p:np.min(np.linalg.norm(bodypts-np.array(p),axis=1)))
  if np.dot(axis,center-np.array(pivot))<0:axis=-axis
  current=math.atan2(axis[1],axis[0]);closed=math.pi/2 if pivot[1]<(low+high)/2 else -math.pi/2
  angle=(current-closed+math.pi)%(2*math.pi)-math.pi
  hull=MultiPoint([(pts[i].x,pts[i].y) for i in indices]).convex_hull
  radius=max(math.hypot(x-pivot[0],y-pivot[1]) for x,y in hull.exterior.coords)
  moving.append({'label':label,'pivot':pivot,'open_angle_deg':math.degrees(angle),'radius_m':radius,'hull':hull,'indices':indices})
 ev.to_mesh_clear();assert moving,(room_key,'No actual moving leaf')
 sweeps=[]
 for leaf in moving:
  angle=leaf['open_angle_deg'];end=math.copysign(max(90,abs(angle)),angle);base=affinity.rotate(leaf['hull'],-angle,origin=leaf['pivot']);count=math.ceil(abs(end)/.5);steps=np.linspace(0,end,count+1)
  # Every intermediate point lies within R*sin(step/2) of a sampled pose.
  pad=leaf['radius_m']*math.sin(math.radians(abs(end)/count/2))+.0001
  sweep=unary_union([affinity.rotate(base,float(v),origin=leaf['pivot']) for v in steps]).buffer(pad,resolution=32)
  sweeps.append(sweep);leaf['sweep_padding_m']=pad
 return {'door':door.name,'wall_x':wallx,'opening_low_y':low,'opening_high_y':high,'outside_sign':outside,'leaves':moving,'sweep':unary_union(sweeps),'open_footprint':unary_union([x['hull'] for x in moving]),'scope':'Actual wood/glass/handle-tag geometry,axis helpers excluded. Geometric frame-jamb hinge inference;closed-to-at-least90deg conservative sampled+bounded swept envelope. No hinge load/manufacturer mechanics certification.'}

def fixture_objects(key):
 return [o for o in bpy.context.scene.objects if o.type=='MESH' and o.get('program_key') in [key+'_vanity',key+'_shower'] and o.get('audit_kind')=='furniture']

def route_free(free,starts,goals,radius):
 centers=free.buffer(-radius,resolution=64)
 for component in polygons(centers):
  start=next((p for p in starts if component.covers(p)),None);goal=next((p for p in goals if component.covers(p)),None)
  if start is not None and goal is not None:return component,start,goal
 return None

def explicit_route(component,start,goal,step=.025):
 # Grid search only within the continuously eroded free component; all links rechecked.
 if component.covers(LineString([start,goal])):return [list(start.coords[0]),list(goal.coords[0])]
 x0,y0,x1,y1=component.bounds;nx=math.ceil((x1-x0)/step);ny=math.ceil((y1-y0)/step)
 def pt(n):return (x0+n[0]*step,y0+n[1]*step)
 valid={(i,j) for i in range(nx+1) for j in range(ny+1) if component.covers(Point(pt((i,j))))}
 def seeds(p):return sorted(valid,key=lambda n:Point(pt(n)).distance(p))[:20]
 ss=[n for n in seeds(start) if component.covers(LineString([start,pt(n)]))];gg={n for n in seeds(goal) if component.covers(LineString([goal,pt(n)]))};assert ss and gg
 queue=[];distance={};previous={}
 for n in ss:distance[n]=Point(pt(n)).distance(start);heapq.heappush(queue,(distance[n]+Point(pt(n)).distance(goal),n))
 finish=None
 while queue:
  _,n=heapq.heappop(queue)
  if n in gg:finish=n;break
  for di,dj in [(1,0),(-1,0),(0,1),(0,-1),(1,1),(1,-1),(-1,1),(-1,-1)]:
   m=(n[0]+di,n[1]+dj)
   if m not in valid or not component.covers(LineString([pt(n),pt(m)])):continue
   value=distance[n]+step*math.hypot(di,dj)
   if value<distance.get(m,float('inf')):distance[m]=value;previous[m]=n;heapq.heappush(queue,(value+Point(pt(m)).distance(goal),m))
 if finish is None:return None
 nodes=[finish]
 while nodes[-1] in previous:nodes.append(previous[nodes[-1]])
 path=[list(start.coords[0])]+[list(pt(n)) for n in nodes[::-1]]+[list(goal.coords[0])]
 return path

def assess_wc(wc,key,program,door=None):
 room=inner_room(program);door=door or door_geometry(key,program);fixtures=fixture_objects(key);shapes=[xybox(o) for o in fixtures];ev,me,wp=evaluated_geometry(wc);body=MultiPoint([(p.x,p.y) for p in wp]).convex_hull;ev.to_mesh_clear();center,seat=seat_centre(wc);forward=wc.matrix_world.to_3x3()@Vector((1,0,0));forward.z=0;forward.normalize();left=Vector((-forward.y,forward.x,0));side=[]
 obstacle=unary_union(shapes+[room.boundary])
 for sign in [1,-1]:
  ray=LineString([(center.x,center.y),(center.x+left.x*sign*8,center.y+left.y*sign*8)]);hit=ray.intersection(obstacle);side.append(Point(center.x,center.y).distance(hit) if not hit.is_empty else None)
 fixed_overlaps=[{'object':o.name,'area_m2':door['sweep'].intersection(shape).area,'clearance_m':door['sweep'].distance(shape)} for o,shape in zip(fixtures,shapes)]
 wc_sweep_gap=body.distance(door['sweep']);wc_sweep_area=body.intersection(door['sweep']).area
 # Bridge follows actual opening, extending far enough beyond both wall faces for the pedestrian disk.
 x=door['wall_x'];domain=room.union(box(x-.7,door['opening_low_y'],x+.7,door['opening_high_y']));case_obstacles=project_fixed_door_parts(door['door'],seat['floor_z'])
 free=domain.difference(unary_union(shapes+[body,door['open_footprint'],case_obstacles]))
 starts=[Point(x+door['outside_sign']*.35,(door['opening_low_y']+door['opening_high_y'])/2+dy) for dy in [0,-.05,.05,-.10,.10]]
 points=list(body.exterior.coords)[:-1];tip=max(px*forward.x+py*forward.y for px,py in points);lat=center.x*left.x+center.y*left.y
 goals=[Point(forward.x*(tip+d)+left.x*(lat+dl),forward.y*(tip+d)+left.y*(lat+dl)) for d in [.32,.36,.40,.45,.50,.55,.60] for dl in [0,-.05,.05,-.1,.1]]
 result=route_free(free,starts,goals,.301);path=None;minimum=None
 if result:
  component,start,goal=result;path=explicit_route(component,start,goal)
  if path:minimum=2*LineString(path).distance(free.boundary)
 max_width=None
 if result:
  low=.301;high=.50
  for _ in range(10):
   mid=(low+high)/2
   if route_free(free,starts,goals,mid):low=mid
   else:high=mid
  max_width=2*low
 lo,hi=bounds(wc);dims=hi-lo
 return {'key':key,'object':wc.name,'bbox_m':[list(lo),list(hi)],'bbox_size_xyz_m':list(dims),'width_m':min(dims.x,dims.y),'depth_m':max(dims.x,dims.y),'height_m':dims.z,'seat_height_m':seat['seat_height_m'],'bowl_centre_m':list(center),'scale':list(wc.scale),'side_left_m':side[0],'side_right_m':side[1],'door':door['door'],'door_leafs':[{'label':r['label'],'pivot_xy_m':r['pivot'],'open_angle_deg':r['open_angle_deg'],'radius_m':r['radius_m'],'sweep_padding_m':r['sweep_padding_m']} for r in door['leaves']],'door_sweep_wc_clearance_m':wc_sweep_gap,'door_sweep_wc_overlap_m2':wc_sweep_area,'door_sweep_fixture_tests':fixed_overlaps,'path_width_required_m':.6,'wc_footprint_xy_m':list(body.exterior.coords),'fixed_door_footprints_xy_m':[list(p.exterior.coords) for p in polygons(case_obstacles)],'fixture_footprints_xy_m':[{'object':o.name,'polygon':list(p.exterior.coords)} for o,p in zip(fixtures,shapes)],'door_sweep_regions_xy_m':[list(p.exterior.coords) for p in polygons(door['sweep'])],'path_polyline_xy_m':path,'path_min_clear_width_m':minimum,'max_certified_path_width_m':max_width,'room_inner_polygon_xy_m':list(room.exterior.coords),'pass':all(v is not None and v>=.4 for v in side) and wc_sweep_area<1e-8 and all(r['area_m2']<1e-8 for r in fixed_overlaps) and minimum is not None and minimum>=.600-1e-5,'scope':'Bowl-centre lateral rays to conservative projected furniture bounds/inner walls. Door swept projection andexplicit swept0.6m pedestrian disk route to WC front,with fully open leaf footprints. Width is a design requirement,not legal compliance. Full3D source rays/mesh audits still required.'}

def set_leaf_angle(room_key,program,label,target_degrees):
 door=door_geometry(room_key,program);leaf=next(r for r in door['leaves'] if r['label']==label);obj=bpy.data.objects[door['door']];obj.data=obj.data.copy();mesh=obj.data;indices=set(leaf['indices']);delta=target_degrees-leaf['open_angle_deg'];pivot=Vector((*leaf['pivot'],0));from mathutils import Matrix
 transform=obj.matrix_world.inverted()@Matrix.Translation(pivot)@Matrix.Rotation(math.radians(delta),4,'Z')@Matrix.Translation(-pivot)@obj.matrix_world
 for face in mesh.polygons:
  selected=sum(i in indices for i in face.vertices)
  assert selected in [0,len(face.vertices)],'Leaf/frame share mixed surface vertices'
 edge_lengths={e.index:(mesh.vertices[e.vertices[0]].co-mesh.vertices[e.vertices[1]].co).length for e in mesh.edges if all(i in indices for i in e.vertices)}
 custom=mesh.has_custom_normals
 normals=[v.vector.copy() for v in mesh.corner_normals] if custom else None
 for i in indices:mesh.vertices[i].co=transform@mesh.vertices[i].co
 mesh.update()
 if custom:
  normal_matrix=transform.to_3x3().inverted().transposed()
  for loop in mesh.loops:
   if loop.vertex_index in indices:normals[loop.index]=(normal_matrix@normals[loop.index]).normalized()
  mesh.normals_split_custom_set(normals)
 errors=[abs((mesh.vertices[mesh.edges[i].vertices[0]].co-mesh.vertices[mesh.edges[i].vertices[1]].co).length-v) for i,v in edge_lengths.items()]
 assert max(errors,default=0)<2e-5
 return {'room':room_key,'door':obj.name,'leaf':label,'old_open_angle_degrees':leaf['open_angle_deg'],'new_open_angle_degrees':target_degrees,'hinge_xy_m':leaf['pivot'],'rigid_vertex_count':len(indices),'max_native_edge_length_error_m':max(errors,default=0),'reason':'Full opening or outward handing to preserve requested600mm route; no leaf scaling or proxy geometry.'}

def lower_small_bathroom_door(program,delta_y=-.10,room_key='102_bathroom1',opening_override=None):
 """Translate existing aperture/door,retile its wall; preserve room outer footprint."""
 from collections import defaultdict
 from shapely.ops import triangulate
 from tile_geometry import grids,tile_solid
 door=bpy.data.objects[DOORS[room_key]];before=door_geometry(room_key,program);low,high=opening_override or (before['opening_low_y'],before['opening_high_y']);wallx=before['wall_x'];changed=[]
 for obj in list(bpy.context.scene.objects):
  if obj.type!='MESH' or not(obj.name.endswith(('.wall','.exterior')) or obj.name=='skirtingboard_support'):continue
  indices=[]
  for v in obj.data.vertices:
   p=obj.matrix_world@v.co
   if abs(p.x-wallx)<.25 and low-.020<=p.y<=high+.020:indices.append(v.index)
  if not indices:continue
  obj.data=obj.data.copy();inverse=obj.matrix_world.inverted()
  for index in indices:
   p=obj.matrix_world@obj.data.vertices[index].co;p.y+=delta_y;obj.data.vertices[index].co=inverse@p
  obj.data.update();changed.append({'object':obj.name,'moved_jamb_vertex_count':len(indices)})
 assert any(x['object']==program['room_id']+'.wall' for x in changed)
 # Move the complete existing native door/casing in translation,not a new stand-in.
 casing_name=door.name.replace('LiteDoorFactory','DoorCasingFactory').replace('GlassPanelDoorFactory','DoorCasingFactory');casing=bpy.data.objects[casing_name]
 for obj in [door,casing]:
  mat=obj.matrix_world.copy();mat.translation.y+=delta_y;obj.matrix_world=mat
 # Crossing a600mm grid edge makes vertex-only tile edits unsafe. Rebuild actual clipped tile solids.
 prefix='Realism_'+program['room_id']+'_wall_tile_';old=[o for o in bpy.context.scene.objects if o.name.startswith(prefix)];assert old;material=old[0].data.materials[0];owner=old[0].get('reference_scene_owner','dual_unit_residential_floor_03');oldnames=[o.name for o in old]
 for obj in old:bpy.data.objects.remove(obj,do_unlink=True)
 wall=bpy.data.objects[program['room_id']+'.wall'];center=Polygon(program['polygon_m']).representative_point();planes=defaultdict(list)
 for face in wall.data.polygons:
  points=[wall.matrix_world@wall.data.vertices[i].co for i in face.vertices];normal=(points[1]-points[0]).cross(points[2]-points[0])
  if normal.length<1e-8:continue
  normal.normalize()
  if abs(normal.z)>.1 or max(abs(normal.x),abs(normal.y))<.99:continue
  axis=0 if abs(normal.x)>.99 else 1;other=1-axis;mid=sum(points,Vector())/len(points)
  if normal.x*(center.x-mid.x)+normal.y*(center.y-mid.y)<=0:continue
  poly=Polygon([(p[other],p.z) for p in points])
  if poly.is_valid and poly.area>1e-7:planes[(axis,round(mid[axis],5),1 if normal[axis]>0 else -1)].append(poly)
 count=0
 for (axis,plane,sign),parts in planes.items():
  normal=Vector((sign,0,0) if axis==0 else (0,sign,0));surface=unary_union(parts)
  def point(u,v):return Vector((plane,u,v) if axis==0 else (u,plane,v))
  for poly in grids(surface):
   tile_solid(prefix+str(count),poly,lambda u,v:point(u,v)+normal*.0015,normal,material,owner);count+=1
 bpy.context.view_layer.update()
 return {'room':room_key,'door':door.name,'casing':casing.name,'translation_m':[0,delta_y,0],'old_opening_y_m':[low,high],'new_opening_y_m':[low+delta_y,high+delta_y],'jamb_geometry_changes':changed,'old_wall_tile_objects':oldnames,'rebuilt_wall_tile_count':count,'reason':'Full native WC plus400mm side clearance makes old lower-jamb throat narrower than600mm. Translate aperture100mm down to free actual route without shrinking fixtures. Outer room footprint unchanged.'}


def project_fixed_door_parts(door_name,floor_z):
 """Clip real triangles to ankle/head band before projection; preserve empty frame opening."""
 door=bpy.data.objects[door_name];case_name=door_name.replace('LiteDoorFactory','DoorCasingFactory').replace('GlassPanelDoorFactory','DoorCasingFactory');objects=[(bpy.data.objects[case_name],False),(door,True)];parts=[]
 def clipped(poly,z,keep_above):
  if not poly:return []
  result=[]
  for a,b in zip(poly,poly[1:]+poly[:1]):
   ina=a.z>=z if keep_above else a.z<=z;inb=b.z>=z if keep_above else b.z<=z
   if ina:result.append(a)
   if ina!=inb:result.append(a+(b-a)*((z-a.z)/(b.z-a.z)))
  return result
 for obj,frame_only in objects:
  ev,mesh,pts=evaluated_geometry(obj);attr=mesh.attributes.get('door_frame');mesh.calc_loop_triangles()
  for tri in mesh.loop_triangles:
   if frame_only and (not attr or any(attr.data[i].value<=.5 for i in tri.vertices)):continue
   vs=clipped([pts[i] for i in tri.vertices],floor_z+.08,True);vs=clipped(vs,floor_z+1.9,False)
   if len(vs)<3:continue
   poly=MultiPoint([(p.x,p.y) for p in vs]).convex_hull
   if not poly.is_empty:parts.append(poly.buffer(.00005,resolution=16))
  ev.to_mesh_clear()
 return unary_union(parts)

