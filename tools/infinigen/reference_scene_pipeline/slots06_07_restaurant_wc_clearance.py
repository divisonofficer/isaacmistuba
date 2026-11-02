"""Correct actual inward WC entry routes exposed by r5 eye-level image."""
import bpy,json,math,sys
from pathlib import Path
from mathutils import Vector,Matrix
T=Path(__file__).parent;R=T.parents[2];sys.path.append('/root/miniconda3/envs/infinigen/lib/python3.11/site-packages')
from shapely.geometry import Polygon,MultiPoint,LineString
from shapely.ops import unary_union
W=R/'out/infinigen_v2/kr_large_restaurant_floor_07_48712507';out=W/'furnished_r6.blend';assert not out.exists();bpy.ops.wm.open_mainfile(filepath=str(W/'furnished_r5.blend'));inv=json.loads((W/'native_product_inventory_r5.json').read_text());changed=[]
def move(p,x,y,angle):
 ox,oy,oz=p['placement_xyz_m'];delta=Matrix.Translation((x,y,oz))@Matrix.Rotation(angle-p['yaw_radians'],4,'Z')@Matrix.Translation((-ox,-oy,-oz))
 for name in p['objects']:o=bpy.data.objects[name];o.matrix_world=delta@o.matrix_world
 changed.append({'objects':p['objects'],'before_xy_yaw':[ox,oy,p['yaw_radians']],'after_xy_yaw':[x,y,angle],'native_scale_preserved':True});p['placement_xyz_m']=[x,y,oz];p['yaw_radians']=angle
south=sorted([p for p in inv['products'] if p['label']=='native_fullsize_toilet' and p['placement_xyz_m'][0]==18],key=lambda p:p['placement_xyz_m'][1]);assert len(south)==3
for p,x in zip(south,[18,19.5,21]):move(p,x,4.35,0)
for p in inv['products']:
 x,y,z=p['placement_xyz_m']
 if p['label']=='native_full_pedestal_basin' and x==21.3:
  if y<5:move(p,18.4 if y<2 else 20.6,.55,math.pi)
  elif y<14:move(p,21.2,12.6,math.pi)
 if p['label']=='native_fullsize_toilet' and x==1:move(p,x,y,math.pi)
for o in list(bpy.data.objects):
 if o.name.startswith('South_WC_partition_') or o.name=='North_WC_partition':bpy.data.objects.remove(o,do_unlink=True)
mat=bpy.data.materials['Sanitary_partition_inferred_cream_laminate'];partitions=[]
def partition(name,x0,y0,x1,y1):
 verts=[(x,y,z) for z in [.11,2.11] for x,y in [(x0,y0),(x1,y0),(x1,y1),(x0,y1)]];me=bpy.data.meshes.new(name);me.from_pydata(verts,[],[(0,3,2,1),(4,5,6,7),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)]);me.materials.append(mat);o=bpy.data.objects.new(name,me);bpy.context.scene.collection.objects.link(o);partitions.append(o)
for x in [18.75,20.25]:partition('South_WC_route_corrected_partition_'+str(x),x,3.1,x+.1,4.89)
partition('North_WC_route_corrected_partition',19.15,15.75,20.8,15.85)
bpy.context.view_layer.update()
# Reserve actual adult-scale fixture/partition-free circulation footprints, not only narrow portal strips.
routes={'south_entry_1m':Polygon([(17.12,2),(21.8,2),(21.8,3),(17.12,3)]),'north_entry_1m':Polygon([(19.12,13.1),(21.7,13.1),(21.7,14.1),(19.12,14.1)]),'north_aisle_1m':Polygon([(20.85,14.1),(21.85,14.1),(21.85,17.85),(20.85,17.85)]),'single_wc_aisle_0p9m':Polygon([(.95,1.25),(1.85,1.25),(1.85,2.5),(.95,2.5)]),'single_wc_portal_transition':Polygon([(.6,2.9),(1.4,2.9),(1.85,2.5),(.95,2.5)])};conflicts=[];support=[]
for p in inv['products']:
 points=[bpy.data.objects[name].matrix_world@v.co for name in p['objects'] for v in bpy.data.objects[name].data.vertices];lo=[min(v[k] for v in points) for k in range(3)];hi=[max(v[k] for v in points) for k in range(3)];p['saved_mesh_bounds_xyz_m']=[lo,hi];p['floor_support_error_m']=lo[2]-p.get('support_surface_z_m',.11);assert abs(p['floor_support_error_m'])<1e-4
 hull=MultiPoint([(v.x,v.y) for v in points]).convex_hull
 for k,route in routes.items():
  area=hull.intersection(route).area
  if area>.001:conflicts.append({'route':k,'product':p['label'],'objects':p['objects'],'area_m2':area})
for o in partitions:
 hull=MultiPoint([(o.matrix_world@v.co).xy for v in o.data.vertices]).convex_hull
 for k,route in routes.items():
  if hull.intersection(route).area>.001:conflicts.append({'route':k,'partition':o.name,'area_m2':hull.intersection(route).area})
assert not conflicts,conflicts
# Native current-pose door diagnostics remain separate; neither doors nor toilets hidden or shrunk.
doors=[]
for o in bpy.data.objects:
 if o.type!='MESH' or 'DoorFactory' not in o.name:continue
 points=[o.matrix_world@v.co for v in o.data.vertices];hull=MultiPoint([(v.x,v.y) for v in points]).convex_hull;hits={k:hull.intersection(route).area for k,route in routes.items() if hull.intersection(route).area>.001}
 if hits:doors.append({'door':o.name,'route_convex_projection_intersections_m2':hits,'limitation':'Conservative whole current-pose native door hull may include handle/frame/empty diagonal; not door swing proof'})
inv['scope']+=' r6 actual r5 WC view exposed middle toilet blocking south inward entry. Native scale preserved:3south toilets moved to northwall-facing-south stalls,basins moved south,1mcentral entry aisle; northpartition shortened for1maisle and basin moved clear ofentry; singleWC toilet rotated towardusableinterior. SingleWC label not accessibility certification.';bpy.ops.wm.save_as_mainfile(filepath=str(out));(W/'native_product_inventory_r6.json').write_text(json.dumps(inv,indent=2));(W/'wc_route_volume_audit_r6.json').write_text(json.dumps({'trigger':'r5 southWC eye-level revealed toilet on inward entry route despite narrow portal-strip passing','changes':changed,'reserved_route_polygons_m':{k:list(p.exterior.coords) for k,p in routes.items()},'fixture_partition_conflicts':conflicts,'native_door_conservative_route_diagnostics':doors,'pass_fixture_partition_route_volumes':not conflicts,'limitations':['Native door current-pose hull diagnostics are separate and conservative; full swing/contained-solid and accessibility approval not claimed','No cubicle-front privacy leaves/hardware yet','Opening and floor-fit audits remain separate'],'photorealism_accepted':False},indent=2));views=[{'name':'south_restroom','location':[21.4,1.5,1.65],'target':[19.3,4.25,.8],'hfov':85,'render_width':768,'samples':24},{'name':'north_restroom','location':[21.45,13.7,1.65],'target':[20,16,.75],'hfov':80,'render_width':768,'samples':24},{'name':'single_restroom','location':[1.45,2.55,1.65],'target':[1,.7,.65],'hfov':85,'render_width':768,'samples':24},{'name':'overview','location':[11,9,35],'target':[11,9,0],'overview':True,'ortho_scale':27,'render_width':768,'samples':16}];(W/'furnished_r6_views.json').write_text(json.dumps(views,indent=2));print('WC_ROUTE_LAYOUT_R6_SAVED',len(changed),'native_door_diagnostics',len(doors),flush=True)
