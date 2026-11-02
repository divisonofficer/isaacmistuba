"""Whole native functional service batch: seating aisles,open booths,reception and real luminaires."""
from pathlib import Path
import sys,json,math,hashlib,copy
T=Path(__file__).parent;sys.argv=['slots06_07_restaurant_services.py','--','large_restaurant_floor_07'];src=(T/'slots06_07_furnish.py').read_text().split('if seed==48712506:')[0].replace("out=W/'furnished_r1.blend'","out=W/'furnished_r11_services.blend'").replace("str(W/'full/scene.blend')","str(W/'furnished_r10_all_doors.blend')");exec(compile(src,str(T/'slots06_07_furnish.py'),'exec'))
from mathutils.bvhtree import BVHTree
sys.path.append('/root/miniconda3/envs/infinigen/lib/python3.11/site-packages');from shapely.geometry import Polygon,box;from shapely.ops import unary_union,triangulate
from cut_surface import remove_box_faces
inv=json.loads((W/'native_product_inventory_r10_all_doors.json').read_text());moves=[]
def move(p,x,y,z=None):
 old=Vector(p['placement_xyz_m']);new=Vector((x,y,old.z if z is None else z));delta=new-old
 for n in p['objects']:bpy.data.objects[n].location+=delta
 p['placement_xyz_m']=list(new)
 for b in p['saved_mesh_bounds_xyz_m']:
  for k in range(3):b[k]+=delta[k]
 moves.append({'objects':p['objects'],'translation_m':list(delta),'native_geometry_no_rescale':True})
# Actual0.9m service aisles require chairs at realistic table reach,not0.85m from compacttablecenter.
for table in [p for p in inv['products'] if p['label']=='native_dining_table_main_4seat']:
 cx,cy,cz=table['placement_xyz_m'];target={7.2:7.05,10.7:9.95,13.6:12.85}[round(cy,1)];ids=set(table['objects'])
 for p in inv['products']:
  x,y,z=p['placement_xyz_m']
  if p['label']=='native_wood_dining_chair' and abs(x-cx)<1 and abs(y-cy)<1.1:move(p,x,target+(.75 if y>cy else -.75))
  if ids.intersection(p.get('support_objects',[])):move(p,x,y+target-cy)
 move(table,cx,target)
# Source booths have broad openfronts. Provisional narrowcenteredports prevented adult access behind real frontchairs.
mainwall=bpy.data.objects['living-room_0/0.wall'];mainwall.data=mainwall.data.copy();booths=[]
for i in range(4):
 left=6+3.25*i;right=left+3.25;xc=(left+right)/2;room=f'dining-room_0/{i+1}';wall=bpy.data.objects[room+'.wall'];wall.data=wall.data.copy();cz=min((bpy.data.objects[room+'.ceiling'].matrix_world@Vector(v)).z for v in bpy.data.objects[room+'.ceiling'].bound_box);cut=[]
 for o in [wall,mainwall]:cut.append({'wall':o.name,'removed_split_faces':remove_box_faces(o,(xc,15,(.11+cz)/2),(3.03,.26,cz-.11+.01))})
 assert sum(r['removed_split_faces']for r in cut)>0;booths.append({'key':'private_north_'+str(i),'axis':1,'inside_face_coordinate_m':15.11,'wall_boundary_coordinate_m':15,'aperture_along_z_m':[left+.11,.11,right-.11,cz],'actual_open_front_width_m':3.03,'cut_evidence':cut})
# Genuine counter/complete computer/staffchair; mainentry and WC public aisles remain on east side.
counter=json.loads((D/'native_products/reception_counter_manifest.json').read_text());place(counter,13.8,2.8,math.pi/2,label='native_reception_counter');cr=rows[-1];bpy.context.view_layer.update();verts=[];faces=[]
for n in cr['objects']:
 o=bpy.data.objects[n];off=len(verts);verts += [o.matrix_world@v.co for v in o.data.vertices];faces += [[off+i for i in p.vertices]for p in o.data.polygons]
ctree=BVHTree.FromPolygons(verts,faces)
monitors=json.loads((R/'data/venue_refs/floor_plans_v3/commercial_office_floor_02/native_monitor110_products/asset_manifest.json').read_text())['assets'];pc=next(e for e in monitors if 'ad9fc592' in e['id']);objs,mats,lo,hi,prof=get(pc);raw=[o.matrix_world@v.co for o in objs for v in o.data.vertices];low=[p for p in raw if p.z<=lo.z+.0003];origin=Vector(((lo.x+hi.x)/2,(lo.y+hi.y)/2,lo.z));foot=[]
for j in range(8):u=Vector((math.cos(j*math.pi/4),math.sin(j*math.pi/4),0));foot.append(Matrix.Rotation(-math.pi/2,4,'Z')@(max(low,key=lambda p:(p-origin).dot(u))-origin))
candidates=[]
for x in [13.6,13.7,13.8,13.9,14.0]:
 for y in [2.65,2.8,2.95]:
  hits=[ctree.ray_cast(Vector((x+q.x,y+q.y,2.5)),Vector((0,0,-1)),3)[0]for q in foot]
  if all(h is not None for h in hits):
   zz=[h.z for h in hits]
   if max(zz)-min(zz)<.002 and .7<max(zz)<1.6:candidates.append((abs(max(zz)-1.05)+.1*abs(x-13.6),x,y,max(zz),zz))
assert candidates,'No actual native counter surface supports full real computer foot';_,px,py,pz,hits=min(candidates);floor=pz;place(pc,px,py,-math.pi/2,label='native_reception_complete_computer');rows[-1]['support_surface_z_m']=pz;rows[-1]['support_objects']=cr['objects'];floor=.11
chairs=json.loads((R/'data/venue_refs/floor_plans_v3/commercial_office_floor_02/real_chair_candidates/asset_candidates_manifest.json').read_text())['assets'];place(chairs[0],12.65,3.9,math.pi/2,label='native_reception_staff_chair')
for objs,*rest in templates.values():
 for o in objs:bpy.data.objects.remove(o,do_unlink=True)
bpy.context.view_layer.update()
for p in rows:
 pp=[bpy.data.objects[n].matrix_world@v.co for n in p['objects']for v in bpy.data.objects[n].data.vertices];p['saved_mesh_bounds_xyz_m']=[[min(v[k]for v in pp)for k in range(3)],[max(v[k]for v in pp)for k in range(3)]];p['floor_support_error_m']=p['saved_mesh_bounds_xyz_m'][0][2]-p.get('support_surface_z_m',.11);assert abs(p['floor_support_error_m'])<1e-4
# True architectural support under broadened booths and the actual northreceptionopen,not floating floor claims.
def floor_union():
 pp=[]
 for o in bpy.data.objects:
  if o.type=='MESH' and o.name.endswith('.floor'):
   for face in o.data.polygons:
    q=Polygon([(o.matrix_world@o.data.vertices[i].co).xy for i in face.vertices])
    if q.is_valid and q.area>1e-8:pp.append(q)
 return unary_union(pp)
floors=floor_union();openaps=booths+[r for r in json.loads((W/'open_passage_actual_wall_apertures_r9.json').read_text())['rows']if r['key']=='reception_north'];thresholds=[];tile=bpy.data.materials['Reference_inferred_terracotta_450mm']
for ap in openaps:
 a,z0,b,z1=ap['aperture_along_z_m'];c=ap['wall_boundary_coordinate_m'];v=ap['inside_face_coordinate_m'];outer=2*c-v;rect=box(a,min(v,outer),b,max(v,outer));missing=rect.difference(floors.buffer(.00001));parts=list(missing.geoms)if hasattr(missing,'geoms')else[missing]
 for j,p in enumerate(parts):
  if p.geom_type!='Polygon'or p.area<1e-7:continue
  vv=[];ff=[]
  for tr in triangulate(p):
   if not p.covers(tr.representative_point()):continue
   cc=list(tr.exterior.coords)[:3];k=len(vv);vv +=[(x,y,.055)for x,y in cc]+[(x,y,.11)for x,y in cc];ff +=[(k,k+2,k+1),(k+3,k+4,k+5)]
  for ring in [p.exterior]+list(p.interiors):
   cc=list(ring.coords)
   for u,vv2 in zip(cc,cc[1:]):k=len(vv);vv +=[(u[0],u[1],.055),(vv2[0],vv2[1],.055),(vv2[0],vv2[1],.11),(u[0],u[1],.11)];ff.append((k,k+1,k+2,k+3))
  me=bpy.data.meshes.new('Architectural_open_threshold');me.from_pydata(vv,[],ff);me.materials.append(tile);o=bpy.data.objects.new('Open_booth_threshold_'+ap['key']+'_'+str(j)+'.floor',me);bpy.context.scene.collection.objects.link(o);thresholds.append({'object':o.name,'actual_filled_area_m2':p.area,'top_z_m':.11})
# Actual reviewed native downlight mesh library;link/update before capturing sourceworld/parent removal.
A=R/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03/real_recessed_light_candidate';asset=A/'functional_unlit.blend';scope=json.loads((A/'review_scope.json').read_text())
with bpy.data.libraries.load(str(asset),link=False)as(src,loaded):loaded.objects=list(scope['objects'])
parts=loaded.objects
for o in parts:bpy.context.scene.collection.objects.link(o)
bpy.context.view_layer.update();source_mats={o:o.matrix_world.copy()for o in parts}
for o in parts:o.parent=None;o.matrix_world=source_mats[o]
bpy.context.view_layer.update();pp=[o.matrix_world@v.co for o in parts for v in o.data.vertices];lo=Vector([min(p[k]for p in pp)for k in range(3)]);hi=Vector([max(p[k]for p in pp)for k in range(3)]);size=hi-lo;assert max(abs(size[k]-scope['actual_dimensions_m'][k])for k in range(3))<1e-5
spec=[('bathroom_0/0',1,1.6,30,3500),('bathroom_0/2',20.4,13.7,40,3500),('bathroom_0/2',20.4,16.5,40,3500),('bathroom_0/1',18.5,2.2,40,3500),('bathroom_0/1',20.5,2.2,40,3500),('office_0/0',14.6,1.7,30,3200),('office_0/0',14.6,3.8,30,3200),('kitchen_0/0',3.8,11.2,40,4000),('kitchen_0/0',3.8,14.1,40,4000),('dining-room_0/0',4.5,2,30,3000),('living-room_0/0',2,5.5,20,3000)]
for i in range(4):spec.append((f'dining-room_0/{i+1}',7.625+3.25*i,16.5,25,3000))
for p in [p for p in inv['products']if p['label']=='native_dining_table_main_4seat']:spec.append(('living-room_0/0',*p['placement_xyz_m'][:2],10,3000))
fixtures=[];ceilings=set()
for i,(room,x,y,power,temp)in enumerate(spec):
 ceiling=bpy.data.objects[room+'.ceiling']
 if ceiling.name not in ceilings:ceiling.data=ceiling.data.copy();ceilings.add(ceiling.name)
 cz=min((ceiling.matrix_world@Vector(v)).z for v in ceiling.bound_box);delta=Vector((x-(lo.x+hi.x)/2,y-(lo.y+hi.y)/2,cz+.004-hi.z));names=[]
 for src in parts:
  o=src.copy();o.data=src.data.copy();bpy.context.scene.collection.objects.link(o);o.matrix_world=Matrix.Translation(delta)@source_mats[src];o.name=f'Restaurant_real_native_downlight_{i:02d}_{src.name}';o['original_asset_id']=scope['asset_id'];o['reference_ceiling_detail']=True;names.append(o.name)
  for j,m in enumerate(o.data.materials):
   if m and '::000'in m.name:
    m=m.copy();o.data.materials[j]=m;bs=next(n for n in m.node_tree.nodes if n.type=='BSDF_PRINCIPLED');bb=m.node_tree.nodes.new('ShaderNodeBlackbody');bb.inputs['Temperature'].default_value=temp;m.node_tree.links.new(bb.outputs['Color'],bs.inputs['Emission Color']);bs.inputs['Emission Strength'].default_value=2
 cut=remove_box_faces(ceiling,(x,y,cz),(.07,.07,.06));assert cut>0,(room,x,y)
 ld=bpy.data.lights.new('Native_downlight_transport_'+str(i),'AREA');ld.shape='DISK';ld.size=.06;ld.use_nodes=True;ld.energy=power;em=next(n for n in ld.node_tree.nodes if n.type=='EMISSION');em.inputs['Strength'].default_value=power;bb=ld.node_tree.nodes.new('ShaderNodeBlackbody');bb.inputs['Temperature'].default_value=temp;ld.node_tree.links.new(bb.outputs['Color'],em.inputs['Color']);lamp=bpy.data.objects.new(ld.name,ld);bpy.context.scene.collection.objects.link(lamp);lamp.location=(x,y,cz-.009)
 fixtures.append({'room':room,'objects':names,'source_asset':str(asset),'native_dimensions_xyz_m':list(size),'native_polygons':scope['native_faces'],'post_generation_scale':False,'ceiling_z_m':cz,'fixture_native_top_z_m':cz+.004,'fixture_native_bottom_z_m':cz+.004-size.z,'cutout_square_m':.07,'round_trim_covers_square_cutout':min(size.x,size.y)>.07*2**.5,'removed_ceiling_faces':cut,'transport_area_light':lamp.name,'transport_area_power':power,'CCT_inferred_K':temp,'photometry':'Approximate transport rig,not manufacturer lumens/IES or calibratedpower. Low2emissionvisible native diffuser plus area at2mmbelowmodel.'})
for o in parts:bpy.data.objects.remove(o,do_unlink=True)
inv['products']+=rows;inv['images']=[preserve_native_packed_image(im)for im in{n.image for m in bpy.data.materials if m.use_nodes for n in m.node_tree.nodes if n.type=='TEX_IMAGE'and n.image}];inv['scope']+=' r11 realValencia17,548triangle receptioncounter,completeChromebasecomputer actual8footrays and genuine staffofficechair. Mainthree rows at7.05/9.95/12.85m withnativechairs0.75m fromtablecenter give~0.95maisles. Referenceinterpretedbroadopenboothfronts replaceprovisional1.083mports obstructedbyfrontchairs;actualnativefrontwalls cut3.03m withgroundedthresholds. Realnative6294face/104.9mmdownlights placed atnative size,actualceilingapertures,explicitinferred transport/CCT—not photometriccalibration. Furniture meshes/UV/nativeimagebytes preserved.'
bpy.context.view_layer.update();bpy.ops.wm.save_as_mainfile(filepath=str(out));(W/'native_product_inventory_r11_services.json').write_text(json.dumps(inv,indent=2));(W/'native_luminaire_inventory_r11.json').write_text(json.dumps({'native_source_sha256':hashlib.sha256(asset.read_bytes()).hexdigest(),'fixtures':fixtures,'source_dimensions_preserved':True,'physical_ceiling_apertures':True,'photorealism_accepted':False},indent=2));(W/'restaurant_whole_services_r11.json').write_text(json.dumps({'source':'furnished_r10_all_doors.blend','candidate':str(out),'rigid_furniture_group_translations':moves,'prior_tabletop_contact_rays_invariant':'native_table_prop_contact_rays_r8.json;commonXYtranslations preserve native contact geometry/heights','new_native_reception_products':rows,'computer_native_foot_contact_heights_m':hits,'booth_open_front_architecture':booths,'actual_missing_floor_thresholds_filled':thresholds,'native_light_fixture_count':len(fixtures),'source_character_gaps':['Privatewhite stone differs from referencedarkwood','Receptioncounter/computerworkstationgenuinebutkeyboard/checkoutequipmentmissing','Commercialkitchenventilation/food/cutlery/practicalpendants/sourceornamentationincomplete','Upperrightenclosed northWCfixture region ambiguous'],'photorealism_accepted':False},indent=2))
# Persist auditable actual scene plan revision only after the native candidate is safely saved.
original=D/'floor_plan_reference_r0.json'
if not original.exists():original.write_bytes((D/'floor_plan.json').read_bytes())
plan=json.loads((D/'floor_plan.json').read_text());wc=json.loads((W/'wc_actual_wall_apertures_r6.json').read_text())['rows'];other=json.loads((W/'remaining_actual_wall_apertures_r9.json').read_text())['rows'];keymap={'single':'accessible_wc','north':'north_wc','south':'south_wc','kitchen':'kitchen','private_south':'private_south','reception':'reception','main_entry':'main'}
for ap in wc+other:
 a,z0,b,z1=ap['aperture_along_z_m'];c=ap['wall_boundary_coordinate_m'];points=[(c,a),(c,b)]if ap['axis']==0 else[(a,c),(b,c)];group='entrance'if ap['key']=='main_entry'else'doors';plan[group][keymap[ap['key']]]['shape']=f'shapely.LineString({points!r})'
for ap in booths:
 a,z0,b,z1=ap['aperture_along_z_m'];plan['opens'][ap['key']]['shape']=f'shapely.LineString({[(a,15),(b,15)]!r})'
ap=next(a for a in openaps if a['key']=='reception_north');a,z0,b,z1=ap['aperture_along_z_m'];plan['opens']['reception_dining']['shape']=f'shapely.LineString({[(a,5),(b,5)]!r})';(D/'floor_plan.json').write_text(json.dumps(plan,indent=2));contract=json.loads((D/'scene_contract.json').read_text());contract.update(revision='plan_r1_actual_native_openings_open_booth_fronts',reference_input_plan='floor_plan_reference_r0.json',actual_candidate=str(out.relative_to(R)));contract['source_uncertainties'].append('Northernbooths interpretedasbroadsemi-privateopenfronts followingnative-size adult table/chair access audit;actual3.03mfrontopenings areauthoredpost-native-shell. Originalinputplan retained. Nativeengineactualdoorholes1.219m differfromprovisionalinputwidths;thisplan now records actualnativeholes.');(D/'scene_contract.json').write_text(json.dumps(contract,indent=2))
from preflight import audit
pre=audit(D);(D/'preflight_layout_r1.json').write_text(json.dumps(pre,indent=2));assert pre['status']=='pass',pre
# Exact body route inputs distinguish0.9mpublic/WC from0.8mprivatebay side circulation.
paths=json.loads((W/'body_route_paths_r10_all_doors.json').read_text());paths=[p for p in paths if p['route']!='main_entry_portal'];paths.append({'route':'main_reception_to_dining','center_polyline_m':[[14.24,.55],[15.2,1.1],[15.2,4.15],[14.2,4.15],[14.2,5.6]],'body_width_m':.9})
for i in range(4):x=6+3.25*i+.525;paths.append({'route':'private_north_'+str(i)+'_side_access','center_polyline_m':[[x,14.35],[x,17.25]],'body_width_m':.8})
(W/'body_route_paths_r11_services.json').write_text(json.dumps(paths,indent=2));(W/'furnished_r11_services_views.json').write_text((W/'furnished_r10_all_doors_views.json').read_text());print('WHOLE_NATIVE_SERVICES_R11_SAVED',len(rows),'realreceptionproducts',len(fixtures),'nativefixtures',pre['status'],flush=True)
