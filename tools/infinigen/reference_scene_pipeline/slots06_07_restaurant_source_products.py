"""Source-verified restroom program and genuine detailed kitchen donor correction."""
from pathlib import Path
import sys,json,copy
T=Path(__file__).parent;sys.argv=['slots06_07_restaurant_source_products.py','--','large_restaurant_floor_07'];src=(T/'slots06_07_furnish.py').read_text().split('if seed==48712506:')[0].replace("out=W/'furnished_r1.blend'","out=W/'furnished_r6_products.blend'").replace("str(W/'full/scene.blend')","str(W/'furnished_r6.blend')");exec(compile(src,str(T/'slots06_07_furnish.py'),'exec'))
sys.path.append('/root/miniconda3/envs/infinigen/lib/python3.11/site-packages');from shapely.geometry import MultiPoint,Polygon
inv=json.loads((W/'native_product_inventory_r6.json').read_text());oldislands=[p for p in inv['products'] if p['label']=='native_kitchen_prep_island'];e=json.loads((D/'native_products/detailed_prep_island_manifest.json').read_text())
for p in oldislands:
 for name in p['objects']:bpy.data.objects.remove(bpy.data.objects[name],do_unlink=True)
 place(e,*p['placement_xyz_m'][:2],p['yaw_radians'],label='native_detailed_kitchen_prep_island')
inv['products']=[p for p in inv['products'] if p not in oldislands]
for objs,*rest in templates.values():
 for o in objs:bpy.data.objects.remove(o,do_unlink=True)
changed=[]
def move(p,x,y,angle=None):
 ox,oy,oz=p['placement_xyz_m'];angle=p['yaw_radians'] if angle is None else angle;M=Matrix.Translation((x,y,oz))@Matrix.Rotation(angle-p['yaw_radians'],4,'Z')@Matrix.Translation((-ox,-oy,-oz))
 for name in p['objects']:o=bpy.data.objects[name];o.matrix_world=M@o.matrix_world
 p['placement_xyz_m']=[x,y,oz];p['yaw_radians']=angle;changed.append(p)
def clone(p,x,y):
 q=copy.deepcopy(p);q['objects']=[]
 for name in p['objects']:
  o=bpy.data.objects[name].copy();o.data=bpy.data.objects[name].data;bpy.context.scene.collection.objects.link(o);o.name='Source_program_'+str(len(rows))+'_'+name;q['objects'].append(o.name)
 move(q,x,y);rows.append(q);return q
north=sorted([p for p in inv['products'] if p['label']=='native_fullsize_toilet' and p['placement_xyz_m'][0]==20],key=lambda p:p['placement_xyz_m'][1]);assert len(north)==2
for p,y in zip(north,[14.55,15.5]):move(p,19.5,y)
clone(north[0],19.5,16.45);clone(north[0],19.5,17.4)
for p in inv['products']:
 if p['label']=='native_fullsize_toilet' and p['placement_xyz_m'][1]==4.35:move(p,p['placement_xyz_m'][0],4.55)
 if p['label']=='native_fullsize_toilet' and p['placement_xyz_m'][0]==1:move(p,1,.45)
nb=next(p for p in inv['products'] if p['label']=='native_full_pedestal_basin' and p['placement_xyz_m'][1]==12.6);clone(nb,20.1,12.6)
sb=sorted([p for p in inv['products'] if p['label']=='native_full_pedestal_basin' and p['placement_xyz_m'][1]==.55],key=lambda p:p['placement_xyz_m'][0]);move(sb[0],18.1,.55);move(sb[1],19.55,.55);clone(sb[0],21,.55)
# Original private south table has three places each long side; original native product allows this at real adult chair width.
for y in [1.15,2.85]:
 p=next(p for p in inv['products'] if p['label']=='native_wood_dining_chair' and abs(p['placement_xyz_m'][0]-3.85)<.01 and abs(p['placement_xyz_m'][1]-y)<.01);clone(p,4.5,y)
for label,ynew,xdiff in [('native_infinigen_dinner_plate',1.74,0),('native_infinigen_dinner_plate',2.26,0),('native_infinigen_stemmed_glass',1.8492,.24),('native_infinigen_stemmed_glass',2.1508,.24)]:
 p=next(p for p in inv['products'] if p['label']==label and p['placement_xyz_m'][1]<3);q=clone(p,4.5+xdiff,ynew)
for o in list(bpy.data.objects):
 if o.name=='North_WC_route_corrected_partition':bpy.data.objects.remove(o,do_unlink=True)
mat=bpy.data.materials['Sanitary_partition_inferred_cream_laminate'];partitions=[]
for y in [15.025,15.975,16.925]:
 verts=[(x,yy,z) for z in [.11,2.11] for x,yy in [(19.15,y),(20.8,y),(20.8,y+.1),(19.15,y+.1)]];me=bpy.data.meshes.new('North_WC_source_program_partition');me.from_pydata(verts,[],[(0,3,2,1),(4,5,6,7),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)]);me.materials.append(mat);o=bpy.data.objects.new(me.name,me);bpy.context.scene.collection.objects.link(o);partitions.append(o)
bpy.context.view_layer.update();routes={k:Polygon(v) for k,v in json.loads((W/'wc_route_volume_audit_r6.json').read_text())['reserved_route_polygons_m'].items()};conflicts=[]
# Re-evaluate changed actual meshes. Unchanged geometry/poses retain the full saved r6 actual-mesh route evidence.
for p in changed+rows:
 points=[bpy.data.objects[name].matrix_world@v.co for name in p['objects'] for v in bpy.data.objects[name].data.vertices];lo=[min(v[k] for v in points) for k in range(3)];hi=[max(v[k] for v in points) for k in range(3)];p['saved_mesh_bounds_xyz_m']=[lo,hi];p['floor_support_error_m']=lo[2]-p.get('support_surface_z_m',.11);assert abs(p['floor_support_error_m'])<1e-4
 hull=MultiPoint([(p.x,p.y) for p in points]).convex_hull
 for k,route in routes.items():
  if hull.intersection(route).area>.001:conflicts.append({'objects':p['objects'],'route':k,'area_m2':hull.intersection(route).area})
for o in partitions:
 h=MultiPoint([(o.matrix_world@v.co).xy for v in o.data.vertices]).convex_hull
 for k,r in routes.items():
  if h.intersection(r).area>.001:conflicts.append({'partition':o.name,'route':k})
assert not conflicts,conflicts
inv['products']+=rows;inv['images']=[preserve_native_packed_image(im) for im in {n.image for m in bpy.data.materials if m.use_nodes for n in m.node_tree.nodes if n.type=='TEX_IMAGE' and n.image}];inv['scope']+=' Native-resolution source reinspection confirms north4toilets/2basins,south3/3,single1/1;full-size native fixture assemblies now match these visible groups.1m northaisle/entry retained. Southprivate6chairs/table settings, not4. Genuine72faceminimalist prep island replaced by31,504face Magnolia native drawer/leg/island product; inferred wooddielectric correction explicit. No commercial-equipment or final photo approval.';bpy.ops.wm.save_as_mainfile(filepath=str(out));(W/'native_product_inventory_r6_products.json').write_text(json.dumps(inv,indent=2));(W/'source_program_and_fixture_routes_r6_products.json').write_text(json.dumps({'source_reinspected':'source.png at native resolution','fixture_program':{'north_wc':{'toilets':4,'basins':2},'south_wc':{'toilets':3,'basins':3},'single_wc':{'toilets':1,'basins':1}},'fixture_native_sizes_preserved':True,'changed_actual_mesh_route_conflicts':conflicts,'prior_full_route_evidence':'wc_route_volume_audit_r6.json','native_door_diagnostics_retained':True,'native_kitchen_island_replacement':e,'limitations':['Door current-pose diagnostics remain separate; full swing and privacy-door hardware not approved','Single WC is not certified accessible','Commercial source equipment,food/cutlery/pendants and decorative source character still incomplete'],'photorealism_accepted':False},indent=2));views=json.loads((W/'furnished_r5_views.json').read_text());wc={v['name']:v for v in json.loads((W/'furnished_r6_views.json').read_text())}
for i,v in enumerate(views):
 name='single_restroom' if v['name']=='accessible_restroom' else v['name']
 if name in wc:views[i]=wc[name]
(W/'furnished_r6_products_views.json').write_text(json.dumps(views,indent=2));print('SOURCE_PROGRAM_R6_PRODUCTS_SAVED',len(rows),'nativeproduct changes',flush=True)
