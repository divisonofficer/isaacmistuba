"""Fresh measured native single-leaf WC doors; fixed frames, rigid leaf/lever hinges, real thresholds."""
import bpy,json,sys,math,copy
from pathlib import Path
from mathutils import Vector,Matrix
from mathutils.bvhtree import BVHTree
R=Path(__file__).resolve().parents[3];sys.path.insert(0,str(R/'modules/infinigen'));sys.path.append('/root/miniconda3/envs/infinigen/lib/python3.11/site-packages')
from infinigen.assets.objects.elements.doors.base import BaseDoorFactory
from shapely.geometry import Polygon,LineString,MultiPoint,box
from shapely.ops import unary_union,triangulate
W=R/'out/infinigen_v2/kr_large_restaurant_floor_07_48712507';source=W/'furnished_r6_products.blend';out=W/'furnished_r7_doors.blend';assert not out.exists();bpy.ops.wm.open_mainfile(filepath=str(source));aps=json.loads((W/'wc_actual_wall_apertures_r6.json').read_text())['rows'];inv=json.loads((W/'native_product_inventory_r6_products.json').read_text());snap={n:(bpy.data.objects[n].matrix_world.copy(),bpy.data.objects[n].data.as_pointer(),len(bpy.data.objects[n].data.vertices),len(bpy.data.objects[n].data.polygons)) for p in inv['products'] for n in p['objects']};moved=[]
# Actual source banquet sits too close to the measured singleWC approach: rigid native translation only.
for p in inv['products']:
 if p['label']=='native_valencia_banquette':
  for n in p['objects']:bpy.data.objects[n].location.y+=.6;moved.append(n)
  p['placement_xyz_m'][1]+=.6;p['saved_mesh_bounds_xyz_m'][0][1]+=.6;p['saved_mesh_bounds_xyz_m'][1][1]+=.6
body=bpy.data.materials.new('Restaurant_measured_native_door_inferred_warm_timber');body.use_nodes=True;bs=body.node_tree.nodes.get('Principled BSDF');bs.inputs['Base Color'].default_value=(.13,.055,.022,1);bs.inputs['Roughness'].default_value=.48;bs.inputs['IOR'].default_value=1.5
metal=bpy.data.materials.new('Restaurant_measured_native_door_satin_steel');metal.use_nodes=True;bs=metal.node_tree.nodes.get('Principled BSDF');bs.inputs['Base Color'].default_value=(.5,.52,.54,1);bs.inputs['Metallic'].default_value=1;bs.inputs['Roughness'].default_value=.26
class Surface:
 def __init__(self,m):self.material=m
 def apply(self,objects,**kwargs):
  for o in objects if isinstance(objects,(tuple,list)) else [objects]:
   if o is not None:o.data.materials.clear();o.data.materials.append(self.material)
rows=[];doorcache=[]
def bounds(points):return Vector([min(p[k] for p in points) for k in range(3)]),Vector([max(p[k] for p in points) for k in range(3)])
for index,ap in enumerate(aps):
 old=bpy.data.objects[ap['native_old_door']];oldpts=[old.matrix_world@v.co for v in old.data.vertices];oldlo,oldhi=bounds(oldpts);oldright=old.data.attributes.get('door_right');old_double=bool(oldright and any(x.value for x in oldright.data));bpy.data.objects.remove(old,do_unlink=True)
 width=ap['aperture_width_m']-.09;height=ap['aperture_height_m']-.056;assert .8<width<1.3 and 1.9<height<2.4
 fac=BaseDoorFactory(48712607+index);fac.width=width;fac.height=height;fac.depth=.045;fac.door_frame_width=.04;fac.has_glass=False;fac.has_louver=False;fac.handle_type='lever';fac.handle_joint='hinge';fac.handle_info_dict={'handle_type':'lever'};fac.door_frame_style='full_frame_square';fac.door_orientation='right' if ap['key']=='single' else 'left';fac.level_type='cylinder';fac.side_bevel=.0015;fac.auto_bevel.amount=.001;fac.surface=Surface(body);fac.handle_surface=Surface(metal);fac.handle_height=1.05;fac.handle_offset=.055
 o=fac.create_asset(apply=True);o.name='Restaurant_native_measured_WC_'+ap['key'];o['audit_kind']='architecture';o['native_factory']='BaseDoorFactory';o['post_generation_rescaling']=False;bpy.context.view_layer.update();M=o.matrix_world.copy();o.parent=None;o.matrix_world=M
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
 o.data.update();bpy.context.view_layer.update();closed=[v.co.copy() for v in o.data.vertices];closedworld=pts(moving);llo,lhi=bounds(pts(leaf));hinge=Vector((0,0,0));hinge[axis]=ap['wall_boundary_coordinate_m'];hinge[along]=lhi[along] if ap['key']=='single' else llo[along];angle=85 if ap['key']=='single' else -90;framefixed=pts(frame)
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
floors=floor_union();thresholds=[];stone=bpy.data.materials['Reference_inferred_cream_stone_600mm']
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
obstacles += [o for o in bpy.data.objects if o.type=='MESH' and (o.name.endswith('.wall') or 'WC_route_corrected_partition' in o.name or 'North_WC_source_program_partition' in o.name)]
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
# Body-route footprints and actual floor coverage, including current-pose native surfaces.
paths={'single':[(1.32,3.6),(1.3,2.7),(1.25,1.4)],'south':[(16.5,2.9),(17.4,2.9),(18.3,2.8),(18.7,2.5),(21.2,2.5)],'north':[(18.5,13.45),(19.5,13.45),(20.5,13.6),(21.35,14),(21.35,17.35)]};route_rows=[]
# Actual cross-sections keep walls hollow rather than filling their bounding hulls.
def sections(o):
 vs=[o.matrix_world@v.co for v in o.data.vertices];lines=[]
 for z in [.5,1.0,1.5]:
  for p in o.data.polygons:
   cs=[vs[i] for i in p.vertices];cross=[]
   for a,b in zip(cs,cs[1:]+cs[:1]):
    if (a.z-z)*(b.z-z)<0:
     q=a+(b-a)*((z-a.z)/(b.z-a.z));cross.append(q.xy)
   if len(cross)>=2:lines.append(LineString(cross))
 return unary_union(lines).buffer(.002) if lines else Polygon()
arch=[o for o in bpy.data.objects if o.type=='MESH' and (o.name.endswith('.wall') or 'WC_route_corrected_partition' in o.name or 'North_WC_source_program_partition' in o.name or o.name.startswith('Restaurant_native_measured_WC_') or any(o.name==ap['native_casing'] for ap in aps))];arch_sections=[(o.name,sections(o)) for o in arch]
for key,points in paths.items():
 corridor=LineString(points).buffer(.45,cap_style=1,join_style=1);fixture_hits=[];arch_hits=[]
 for p in inv['products']:
  lo,hi=p['saved_mesh_bounds_xyz_m'];bbox=box(lo[0],lo[1],hi[0],hi[1])
  if not bbox.intersects(corridor):continue
  ps=[bpy.data.objects[n].matrix_world@v.co for n in p['objects'] for v in bpy.data.objects[n].data.vertices];h=MultiPoint([v.xy for v in ps]).convex_hull;area=h.intersection(corridor).area
  if area>1e-4:fixture_hits.append({'objects':p['objects'],'area_m2':area})
 for name,g in arch_sections:
  area=g.intersection(corridor).area
  if area>1e-4:arch_hits.append({'object':name,'section_intersection_m2':area})
 unsupported=corridor.difference(floors.buffer(.002)).area;route_rows.append({'route':key,'center_polyline_m':points,'body_width_m':.9,'actual_floor_unsupported_area_m2':unsupported,'fixture_convex_footprint_hits':fixture_hits,'actual_arch_body_height_surface_hits':arch_hits,'pass':unsupported<.001 and not fixture_hits and not arch_hits})
for n,(M,ptr,nv,np) in snap.items():
 o=bpy.data.objects[n];assert o.data.as_pointer()==ptr and len(o.data.vertices)==nv and len(o.data.polygons)==np,n
 if n not in moved:assert max(abs(M[i][j]-o.matrix_world[i][j]) for i in range(4) for j in range(4))<1e-6,n
bpy.ops.wm.save_as_mainfile(filepath=str(out));inv['scope']+=' r7 replaces three measured inappropriate native WC double assemblies with freshly generated dimensioned BaseDoorFactorysingleleaf/fullframesquare; no postgenerationrescale. Native fixedframesstayfixed,leaf+lever only rigidhinge. Actual missing threshold floor supported by55mmstone solids. Banquette moved0.6m north to clear singleWC approach;native furniture data/counts unchanged.';(W/'native_product_inventory_r7_doors.json').write_text(json.dumps(inv,indent=2));doc={'source':str(source),'candidate':str(out),'actual_aperture_evidence':'wc_actual_wall_apertures_r6.json','native_doors':rows,'architectural_thresholds':thresholds,'sampled_sweeps':sweep,'body_routes':route_rows,'unrelated_native_furniture_meshes_and_matrices_unchanged_except_declared_banquette_translation':True,'post_generation_leaf_or_furniture_rescaling':False,'pass_sampled_sweep':all(not r['actual_triangle_hits'] for r in sweep),'pass_body_routes':all(r['pass'] for r in route_rows),'photorealism_accepted':False,'limitations':['37sampled leaf poses and actual triangle surfaces,not continuous contained-solid proof','0.9mbody footprints are conservative,not accessibility certification','Privacy cubicle leaves/hardware and whole-scene photo acceptance still missing']};(W/'native_wc_door_install_and_routes_r7.json').write_text(json.dumps(doc,indent=2));views=json.loads((W/'furnished_r6_products_views.json').read_text());(W/'furnished_r7_doors_views.json').write_text(json.dumps(views,indent=2));print('MEASURED_NATIVE_WC_DOORS_SAVED',doc['pass_sampled_sweep'],doc['pass_body_routes'],route_rows,flush=True)
