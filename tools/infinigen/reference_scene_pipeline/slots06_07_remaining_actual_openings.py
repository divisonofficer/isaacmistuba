import bpy,json,sys
from pathlib import Path
sys.path.append('/root/miniconda3/envs/infinigen/lib/python3.11/site-packages');from shapely.geometry import Polygon,box,Point;from mathutils import Vector;from shapely.ops import unary_union
R=Path(__file__).resolve().parents[3];W=R/'out/infinigen_v2/kr_large_restaurant_floor_07_48712507';source=W/'furnished_r9_clearance.blend';bpy.ops.wm.open_mainfile(filepath=str(source));rows=[]
cases=[('kitchen','kitchen_0/0.wall',0,5.89,9.7,None),('private_south','dining-room_0/0.wall',0,6.89,2.1,None),('reception','office_0/0.wall',0,12.11,2.25,None),('main_entry','office_0/0.wall',1,.11,14.2,None)]
for key,wall,axis,target,alongcenter,door in cases:
 o=bpy.data.objects[wall];bpy.context.view_layer.update();vs=[o.matrix_world@v.co for v in o.data.vertices];planes=[]
 for face in o.data.polygons:
  vv=[vs[i] for i in face.vertices];coords=[v[axis] for v in vv]
  if max(coords)-min(coords)<1e-4:planes.append(sum(coords)/len(coords))
 actual=min(planes,key=lambda v:abs(v-target));assert abs(actual-target)<.04,(key,actual,target);along=1-axis;polys=[]
 for face in o.data.polygons:
  vv=[vs[i] for i in face.vertices]
  if max(abs(v[axis]-actual) for v in vv)>1e-4:continue
  p=Polygon([(v[along],v.z) for v in vv])
  if p.is_valid and p.area>1e-7:polys.append(p)
 surface=unary_union(polys);x0,z0,x1,z1=surface.bounds;missing=box(x0,z0,x1,z1).difference(surface);parts=list(missing.geoms) if hasattr(missing,'geoms') else [missing];hole=next(p for p in parts if p.buffer(.001).contains(Point(alongcenter,1.0)));a,b,c,d=hole.bounds;assert .65<c-a<4 and 1.8<d-b<3.5,(key,hole.bounds);boundary={'kitchen':6,'private_south':7,'reception':12,'main_entry':0}[key];center=Vector((boundary,(a+c)/2,1)) if axis==0 else Vector(((a+c)/2,boundary,1));candidates=[o for o in bpy.data.objects if o.type=='MESH' and 'DoorCasingFactory' in o.name];casing=min(candidates,key=lambda o:((o.matrix_world.translation-center).xy).length);suffix=casing.name.removeprefix('DoorCasingFactory');matches=[o.name for o in bpy.data.objects if o.type=='MESH' and 'DoorFactory' in o.name and 'Casing'not in o.name and o.name.endswith(suffix)];assert len(matches)==1,(key,casing.name,matches);door=matches[0];(print('MATCH_PORTAL',key,door,flush=True));rows.append({'key':key,'wall':wall,'axis':axis,'inside_face_coordinate_m':actual,'wall_boundary_coordinate_m':boundary,'aperture_along_z_m':[a,b,c,d],'aperture_width_m':c-a,'aperture_height_m':d-b,'aperture_polygon':list(hole.exterior.coords),'native_old_door':door,'native_casing':casing.name if casing else None})
(W/'remaining_actual_wall_apertures_r9.json').write_text(json.dumps({'source':str(source),'rows':rows,'scope':'Actual coplanar native wall face triangles union/subtraction,not plan input widths. Physical fit still pending.'},indent=2));print('REMAINING_ACTUAL_APERTURES',[(r['key'],r['aperture_width_m'],r['aperture_height_m']) for r in rows],flush=True)
