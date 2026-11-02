import bpy,json,sys
from pathlib import Path
from mathutils import Vector
sys.path.append('/root/miniconda3/envs/infinigen/lib/python3.11/site-packages');from shapely.geometry import Polygon,box,Point;from shapely.ops import unary_union
R=Path(__file__).resolve().parents[3];D=R/'data/venue_refs/floor_plans_v3/industrial_workshop_floor_06';W=R/'out/infinigen_v2/kr_industrial_workshop_floor_06_48712506';source=W/'furnished_r2.blend';bpy.ops.wm.open_mainfile(filepath=str(source));mapping=json.loads((D/'room_mapping.json').read_text());rows=[];cases=[('south_entry','entrance','southcentral_machine_bay',1,.11,9.5,0),('west_core','opens','west_main_workshop',0,6.89,8,7),('east_core','opens','east_main_workshop',0,12.11,8,12),('central_core','opens','central_main_workshop',1,9.11,9.5,9),('south_core','opens','southcentral_machine_bay',1,5.89,9.5,6),('west_south','opens','southwest_machine_bay',1,6.89,5.6,7),('east_south','opens','southeast_machine_bay',1,6.89,13.4,7)]
for key,group,room,axis,target,center,boundary in cases:
 o=bpy.data.objects[mapping[room]['room_id']+'.wall'];bpy.context.view_layer.update();vs=[o.matrix_world@v.co for v in o.data.vertices];planes=[]
 for f in o.data.polygons:
  vv=[vs[i]for i in f.vertices]
  if max(v[axis]for v in vv)-min(v[axis]for v in vv)<1e-4:planes.append(sum(v[axis]for v in vv)/len(vv))
 plane=min(planes,key=lambda v:abs(v-target));assert abs(plane-target)<.04;polys=[]
 for f in o.data.polygons:
  vv=[vs[i]for i in f.vertices]
  if max(abs(v[axis]-plane)for v in vv)>1e-4:continue
  p=Polygon([(v[1-axis],v.z)for v in vv])
  if p.is_valid and p.area>1e-8:polys.append(p)
 g=unary_union(polys);x0,z0,x1,z1=g.bounds;missing=box(x0,z0,x1,z1).difference(g);parts=list(missing.geoms)if hasattr(missing,'geoms')else[missing];hole=next(p for p in parts if p.buffer(.001).contains(Point(center,1)));a,b,c,d=hole.bounds;assert .65<c-a<4 and 1.8<d-b<3.7;row={'key':key,'group':group,'room':room,'wall':o.name,'axis':axis,'inside_face_coordinate_m':plane,'wall_boundary_coordinate_m':boundary,'aperture_along_z_m':[a,b,c,d],'aperture_width_m':c-a,'aperture_height_m':d-b}
 if group=='entrance':
  casings=[o for o in bpy.data.objects if o.type=='MESH'and'DoorCasingFactory'in o.name];assert len(casings)==1;ca=casings[0];suffix=ca.name.removeprefix('DoorCasingFactory');matches=[o.name for o in bpy.data.objects if o.type=='MESH'and'DoorFactory'in o.name and'Casing'not in o.name and o.name.endswith(suffix)];assert len(matches)==1;row.update(native_casing=ca.name,native_old_door=matches[0])
 rows.append(row)
(W/'actual_openings_r2.json').write_text(json.dumps({'source':str(source),'rows':rows,'scope':'Actual native wallface geometry,not inputline assumptions. Sourcegroundentry inferred,not referenceverified.'},indent=2));print('WORKSHOP_ACTUAL_OPENINGS',[(r['key'],r['aperture_width_m'],r['aperture_height_m'])for r in rows],flush=True)
