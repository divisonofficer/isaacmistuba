"""Fresh measured native single-leaf WC doors; fixed frames, rigid leaf/lever hinges, real thresholds."""
import bpy,json,sys,math,copy
from pathlib import Path
from mathutils import Vector,Matrix
from mathutils.bvhtree import BVHTree
R=Path(__file__).resolve().parents[3];sys.path.insert(0,str(R/'modules/infinigen'));sys.path.append('/root/miniconda3/envs/infinigen/lib/python3.11/site-packages')
from infinigen.assets.objects.elements.doors.base import BaseDoorFactory
from shapely.geometry import Polygon,LineString,MultiPoint,box
from shapely.ops import unary_union,triangulate
W=R/'out/infinigen_v2/kr_industrial_workshop_floor_06_48712506';source=W/'furnished_r2.blend';out=W/'furnished_r3_entry.blend';assert not out.exists();bpy.ops.wm.open_mainfile(filepath=str(source));aps=json.loads((W/'actual_openings_r2.json').read_text())['rows'];inv=json.loads((W/'native_product_inventory_r2.json').read_text());snap={n:(bpy.data.objects[n].matrix_world.copy(),bpy.data.objects[n].data.as_pointer(),len(bpy.data.objects[n].data.vertices),len(bpy.data.objects[n].data.polygons)) for p in inv['products'] for n in p['objects']};moved=[]
body=bpy.data.materials.new('Restaurant_measured_native_door_inferred_warm_timber');body.use_nodes=True;bs=body.node_tree.nodes.get('Principled BSDF');bs.inputs['Base Color'].default_value=(.13,.055,.022,1);bs.inputs['Roughness'].default_value=.48;bs.inputs['IOR'].default_value=1.5
metal=bpy.data.materials.new('Restaurant_measured_native_door_satin_steel');metal.use_nodes=True;bs=metal.node_tree.nodes.get('Principled BSDF');bs.inputs['Base Color'].default_value=(.5,.52,.54,1);bs.inputs['Metallic'].default_value=1;bs.inputs['Roughness'].default_value=.26
class Surface:
 def __init__(self,m):self.material=m
 def apply(self,objects,**kwargs):
  for o in objects if isinstance(objects,(tuple,list)) else [objects]:
   if o is not None:o.data.materials.clear();o.data.materials.append(self.material)
rows=[];doorcache=[]
def bounds(points):return Vector([min(p[k] for p in points) for k in range(3)]),Vector([max(p[k] for p in points) for k in range(3)])
allaps=aps;aps=[a for a in aps if a['group']=='entrance']
# Rigid relocation only: native drill press clears actual measured entrance body path.
relocated=[]
for p in inv['products']:
 if p['label']=='native_drill_press' and p['placement_xyz_m'][:2]==[10,1]:
  for n in p['objects']:bpy.data.objects[n].matrix_world=Matrix.Translation(Vector((.65,.3,0)))@bpy.data.objects[n].matrix_world
  p['placement_xyz_m'][0]+=.65;p['placement_xyz_m'][1]+=.3;relocated.append(p['objects'])
bpy.context.view_layer.update()
for index,ap in enumerate(aps):
 old=bpy.data.objects[ap['native_old_door']];oldpts=[old.matrix_world@v.co for v in old.data.vertices];oldlo,oldhi=bounds(oldpts);oldright=old.data.attributes.get('door_right');old_double=bool(oldright and any(x.value for x in oldright.data));bpy.data.objects.remove(old,do_unlink=True)
 width=ap['aperture_width_m']-.09;height=ap['aperture_height_m']-.056;assert .8<width<1.3 and 1.9<height<2.4
 fac=BaseDoorFactory(48712707+index);fac.width=width;fac.height=height;fac.depth=.045;fac.door_frame_width=.04;fac.has_glass=False;fac.has_louver=False;fac.handle_type='lever';fac.handle_joint='hinge';fac.handle_info_dict={'handle_type':'lever'};fac.door_frame_style='full_frame_square';fac.door_orientation='left';fac.level_type='cylinder';fac.side_bevel=.0015;fac.auto_bevel.amount=.001;fac.surface=Surface(body);fac.handle_surface=Surface(metal);fac.handle_height=1.05;fac.handle_offset=.055
 o=fac.create_asset(apply=True);o.name='Workshop_native_measured_portal_'+ap['key'];o['audit_kind']='architecture';o['native_factory']='BaseDoorFactory';o['post_generation_rescaling']=False;bpy.context.view_layer.update();M=o.matrix_world.copy();o.parent=None;o.matrix_world=M
 if ap['axis']==1:o.matrix_world=Matrix.Rotation(-math.pi/2,4,'Z')@o.matrix_world
 used={i for f in o.data.polygons for i in f.vertices};frame=[i for i in used if o.data.attributes['door_frame'].data[i].value];moving=[i for i in used if o.data.attributes['door_left'].data[i].value];leaf=[i for i in used if o.data.attributes['door'].data[i].value];assert frame and moving and leaf and not set(frame)&set(moving)
 def pts(ids):return [o.matrix_world@o.data.vertices[i].co for i in ids]
 flo,fhi=bounds(pts(frame));a,z0,b,z1=ap['aperture_along_z_m'];axis=ap['axis'];along=1-axis;delta=Vector((0,0,z1-.003-fhi.z));delta[axis]=ap['wall_boundary_coordinate_m']-(flo[axis]+fhi[axis])/2;delta[along]=(a+b)/2-(flo[along]+fhi[along])/2;o.matrix_world=Matrix.Translation(delta)@o.matrix_world;bpy.context.view_layer.update();inverse=o.matrix_world.inverted();llo,lhi=bounds(pts(leaf));floor=.11;shift=floor+.008-llo.z
 for i in moving:o.data.vertices[i].co=inverse@(o.matrix_world@o.data.vertices[i].co+Vector((0,0,shift)))
 # Embed the native fixed lower sill beneath the actual finished floor, no leaf/frame width scaling.
 embedded=[]
 for i in frame:
  p=o.matrix_world@o.data.vertices[i].co
  if p.z<floor+.03:o.data.vertices[i].co=inverse@(p-Vector((0,0,.04)));embedded.append(i)
 o.data.update();bpy.context.view_layer.update();closed=[v.co.copy() for v in o.data.vertices];closedworld=pts(moving);llo,lhi=bounds(pts(leaf));hinge=Vector((0,0,0));hinge[axis]=ap['wall_boundary_coordinate_m'];hinge[along]=llo[along];angle=90;framefixed=pts(frame)
 for i,p in zip(moving,closedworld):o.data.vertices[i].co=inverse@(hinge+Matrix.Rotation(math.radians(angle),4,'Z')@(p-hinge))
 o.data.update();bpy.context.view_layer.update();assert max((p-q).length for p,q in zip(framefixed,pts(frame)))<1e-6;newlo,newhi=bounds(pts(leaf));f0,f1=bounds(pts(frame));handle=o.data.attributes.get('handle');hs=[i for i in used if handle and handle.data[i].value];h0,h1=bounds(pts(hs));row={'key':ap['key'],'new_object':o.name,'removed_measured_inappropriate_old_assembly':ap['native_old_door'],'old_native_double_attribute':old_double,'old_bbox_xyz_m':[list(oldlo),list(oldhi)],'kept_original_casing':ap['native_casing'],'actual_wall_aperture_width_height_m':[ap['aperture_width_m'],ap['aperture_height_m']],'requested_native_leaf_width_height_depth_m':[width,height,.045],'frame_profile_width_m':.04,'post_generation_rescaling':False,'frame_bbox_xyz_m':[list(f0),list(f1)],'open_leaf_bbox_xyz_m':[list(newlo),list(newhi)],'floor_gap_m':newlo.z-floor,'header_rough_gap_m':z1-f1.z,'side_rough_gap_m':(ap['aperture_width_m']-(f1[along]-f0[along]))/2,'open_degrees':angle,'hinge_world_m':list(hinge),'handle_bbox_xyz_m':[list(h0),list(h1)],'frame_fixed_during_articulation':True,'embedded_fixed_lower_frame_vertex_count':len(embedded),'native_polygons':len(o.data.polygons)};rows.append(row);doorcache.append((o,closedworld,moving,hinge,angle,framefixed,frame))
# Floor support at actual openings: fill only absent native-floor footprint with real architectural stone threshold solids.
def floor_union():
 polys=[]
 for o in bpy.data.objects:
  if o.type=='MESH' and o.name.endswith('.floor'):
   for p in o.data.polygons:
    q=Polygon([(o.matrix_world@o.data.vertices[i].co).xy for i in p.vertices])
    if q.is_valid and q.area>1e-7:polys.append(q)
 return unary_union(polys)
floors=floor_union();thresholds=[];stone=bpy.data.materials['Reference_inferred_worn_industrial_concrete'];aps=allaps
for ap in aps:
 a,z0,b,z1=ap['aperture_along_z_m'];c=ap['wall_boundary_coordinate_m'];inside=ap['inside_face_coordinate_m'];outer=2*c-inside;rect=box(min(outer,inside),a,max(outer,inside),b) if ap['axis']==0 else box(a,min(outer,inside),b,max(outer,inside));missing=rect.difference(floors.buffer(.00001));parts=list(missing.geoms) if hasattr(missing,'geoms') else [missing]
 for j,p in enumerate(parts):
  if p.area<1e-7 or p.geom_type!='Polygon':continue
  verts=[];faces=[]
  for tr in triangulate(p):
   if not p.covers(tr.representative_point()):continue
   coords=list(tr.exterior.coords)[:3];k=len(verts);verts += [(x,y,.055) for x,y in coords]+[(x,y,.11) for x,y in coords];faces += [(k,k+2,k+1),(k+3,k+4,k+5)]
  for ring in [p.exterior]+list(p.interiors):
   cc=list(ring.coords)
   for u,v in zip(cc,cc[1:]):k=len(verts);verts += [(u[0],u[1],.055),(v[0],v[1],.055),(v[0],v[1],.11),(u[0],u[1],.11)];faces.append((k,k+1,k+2,k+3))
  me=bpy.data.meshes.new('Native_arch_threshold_'+ap['key']);me.from_pydata(verts,[],faces);me.materials.append(stone);o=bpy.data.objects.new('WC_threshold_'+ap['key']+'_'+str(j)+'.floor',me);bpy.context.scene.collection.objects.link(o);thresholds.append({'object':o.name,'area_m2':p.area,'top_z_m':.11,'thickness_m':.055})
bpy.context.view_layer.update();floors=floor_union()
# Sample actual native moving-leaf+lever triangles against nearby real furniture and architectural walls/partitions.
obstacles=[]
for p in inv['products']:
 for n in p['objects']:obstacles.append(bpy.data.objects[n])
obstacles += [o for o in bpy.data.objects if o.type=='MESH' and (o.name.endswith('.wall') or 'WC_route_corrected_partition' in o.name or 'North_WC_source_program_partition' in o.name or o.name.startswith('Workshop_native_measured_'))]
cache={}
def tree_and_bounds(o):
 if o.name not in cache:
  ps=[o.matrix_world@v.co for v in o.data.vertices];lo,hi=bounds(ps);cache[o.name]=(BVHTree.FromPolygons(ps,[list(p.vertices) for p in o.data.polygons]),lo,hi)
 return cache[o.name]
sweep=[]
for o,closedworld,moving,hinge,angle,framefixed,frame in doorcache:
 inverse=o.matrix_world.inverted();moving_set=set(moving);polys=[list(p.vertices) for p in o.data.polygons if all(i in moving_set for i in p.vertices)];raw=[o.matrix_world@v.co for v in o.data.vertices];states=[];hits=[]
 for step in range(37):
  deg=angle*step/36;rot=Matrix.Rotation(math.radians(deg),4,'Z');ps=raw.copy()
  for i,p in zip(moving,closedworld):ps[i]=hinge+rot@(p-hinge)
  lo,hi=bounds([ps[i] for i in moving]);t=BVHTree.FromPolygons(ps,polys)
  for other in obstacles:
   if other==o:continue
   bbox=[other.matrix_world@Vector(v) for v in other.bound_box];q0,q1=bounds(bbox)
   if not all(min(hi[k],q1[k])-max(lo[k],q0[k])>1e-5 for k in range(3)):continue
   ot,_,_=tree_and_bounds(other);count=len(t.overlap(ot))
   if count:hits.append({'degrees':deg,'object':other.name,'triangle_pairs':count})
  states.append(deg)
 sweep.append({'door':o.name,'sampled_degrees':states,'actual_triangle_hits':hits,'scope':'37rigidpose samples against actual nearby furniture,walls and WCpartitions. Native frame/hinge/trim intentional contacts excluded; continuous mathematical sweep/contained solids not certified.'})

# Repaint native architectural trim coherently; catalogue furniture UV/ORM/images stay untouched.
casings=[]
for o in bpy.data.objects:
 if o.type=='MESH' and 'DoorCasingFactory' in o.name:
  before=[m.name for m in o.data.materials if m];o.data=o.data.copy();o.data.materials.clear();o.data.materials.append(body);casings.append({'object':o.name,'before_materials':before,'after_material':body.name,'authority':'Explicit inferred warm matte timber/paint architectural finish,not measured. Geometry/UV unchanged.'})

for p in inv['products']:
 ps=[bpy.data.objects[n].matrix_world@v.co for n in p['objects']for v in bpy.data.objects[n].data.vertices];p['saved_mesh_bounds_xyz_m']=[[min(v[k]for v in ps)for k in range(3)],[max(v[k]for v in ps)for k in range(3)]]
paths=[{'route':n,'center_polyline_m':ps}for n,ps in [('entry_to_core',[[9.48588,.55],[9.48588,7.5]]),('core_to_north',[[9.48588,7.5],[9.48588,10]]),('core_to_west',[[9.48588,7.7],[6.1,8],[5.6,8]]),('west_to_southwest',[[5.6,8],[5.6,5.8]]),('core_to_east',[[9.48588,7.7],[13,8],[13.4,8.2]]),('east_to_southeast',[[13.4,8.2],[13.4,6.45],[15.25,6.45],[15.25,4.5]])]]
bpy.ops.wm.save_as_mainfile(filepath=str(out));(W/'native_product_inventory_r3_entry.json').write_text(json.dumps(inv,indent=2));(W/'body_route_paths_r3_entry.json').write_text(json.dumps(paths,indent=2));(W/'workshop_measured_entry_r3.json').write_text(json.dumps({'source':str(source),'candidate':str(out),'native_doors':rows,'architectural_thresholds':thresholds,'sampled_sweeps':sweep,'pass_sampled_sweep':all(not r['actual_triangle_hits']for r in sweep),'rigid_drill_relocations':relocated,'post_generation_scaling':False,'source_entry_verified':False,'limitations':['Groundfloor external entry remains inferred from circulation; central reference stair/service reserve unresolved','Heavyindustrial machine acquisition gap remains','37sampled actual triangle poses, not continuous solids certification'],'photorealism_accepted':False},indent=2));(W/'furnished_r3_entry_views.json').write_text(json.dumps(json.loads((W/'furnished_r2_views.json').read_text())+json.loads((W/'furnished_r2_full_views.json').read_text()),indent=2));print('WORKSHOP_MEASURED_ENTRY_SAVED',flush=True)
