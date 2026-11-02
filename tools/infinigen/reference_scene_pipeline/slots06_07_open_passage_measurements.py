import bpy,json,sys
from pathlib import Path
sys.path.append('/root/miniconda3/envs/infinigen/lib/python3.11/site-packages');from shapely.geometry import Polygon,box,Point;from shapely.ops import unary_union
R=Path(__file__).resolve().parents[3];W=R/'out/infinigen_v2/kr_large_restaurant_floor_07_48712507';source=W/'furnished_r9_clearance.blend';bpy.ops.wm.open_mainfile(filepath=str(source));rows=[]
cases=[('private_north_'+str(i),'dining-room_0/'+str(i+1)+'.wall',1,15.11,7.6+3.25*i,'')for i in range(4)]+[('reception_north','office_0/0.wall',1,4.89,14,'')]
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
 surface=unary_union(polys);x0,z0,x1,z1=surface.bounds;missing=box(x0,z0,x1,z1).difference(surface);parts=list(missing.geoms) if hasattr(missing,'geoms') else [missing];hole=next(p for p in parts if p.buffer(.001).contains(Point(alongcenter,1.0)));a,b,c,d=hole.bounds;assert .65<c-a<4 and 1.8<d-b<3.5,(key,hole.bounds);casing=bpy.data.objects.get(door.replace('LiteDoorFactory','DoorCasingFactory'));rows.append({'key':key,'wall':wall,'axis':axis,'inside_face_coordinate_m':actual,'wall_boundary_coordinate_m':15 if key.startswith('private') else 5,'aperture_along_z_m':[a,b,c,d],'aperture_width_m':c-a,'aperture_height_m':d-b,'aperture_polygon':list(hole.exterior.coords),'native_old_door':door,'native_casing':casing.name if casing else None})
(W/'open_passage_actual_wall_apertures_r9.json').write_text(json.dumps({'source':str(source),'rows':rows,'scope':'Actual coplanar native wall face triangles union/subtraction,not plan input widths. Physical fit still pending.'},indent=2));print('OPEN_PASSAGE_ACTUAL_APERTURES',[(r['key'],r['aperture_width_m'],r['aperture_height_m']) for r in rows],flush=True)
