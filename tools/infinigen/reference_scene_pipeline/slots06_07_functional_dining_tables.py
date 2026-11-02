"""Native-size four-seat table products replace oversized six-seat donors; real prop contact rays."""
from pathlib import Path
import sys,json,math
T=Path(__file__).parent;sys.argv=['slots06_07_functional_dining_tables.py','--','large_restaurant_floor_07'];src=(T/'slots06_07_furnish.py').read_text().split('if seed==48712506:')[0].replace("out=W/'furnished_r1.blend'","out=W/'furnished_r8_tables.blend'").replace("str(W/'full/scene.blend')","str(W/'furnished_r7_doors.blend')");exec(compile(src,str(T/'slots06_07_furnish.py'),'exec'))
from mathutils.bvhtree import BVHTree
inv=json.loads((W/'native_product_inventory_r7_doors.json').read_text());entries={e['role']:e for e in json.loads((D/'native_products/functional_compact_tables_manifest.json').read_text())['assets']};tables=[p for p in inv['products'] if p['label']=='native_dining_table' and p['placement_xyz_m'][1]>5];changed=[];toptrees={};prop_groups=[]
def shift(p,target):
 old=Vector(p['placement_xyz_m']);delta=Vector(target)-old
 for n in p['objects']:bpy.data.objects[n].location+=delta
 p['placement_xyz_m']=list(target)
 if 'saved_mesh_bounds_xyz_m' in p:
  for b in p['saved_mesh_bounds_xyz_m']:
   for k in range(3):b[k]+=delta[k]
 changed.append(p)
for table in tables:
 cx,cy,cz=table['placement_xyz_m'];private=cy>15;role='private_4seat' if private else 'main_4seat';targetx=cx-.1 if abs(cx-17.3)<.01 and abs(cy-13.6)<.01 else cx;oldnames=set(table['objects']);place(entries[role],targetx,cy,label='native_dining_table_'+role);new=rows[-1];newtop=.11+new['native_dimensions_xyz_m'][2];bpy.context.view_layer.update()
 if role not in toptrees:
  vertices=[];polygons=[]
  for n in new['objects']:
   o=bpy.data.objects[n];offset=len(vertices);vertices += [o.matrix_world@v.co-Vector((targetx,cy,.11)) for v in o.data.vertices];polygons += [[offset+i for i in p.vertices] for p in o.data.polygons]
  toptrees[role]=BVHTree.FromPolygons(vertices,polygons)
 props=[]
 for p in inv['products']:
  x,y,z=p['placement_xyz_m']
  if p['label']=='native_wood_dining_chair' and abs(x-cx)<1 and abs(y-cy)<1.1:shift(p,(targetx+(.38 if private else .45)*(1 if x>cx else -1),y,z))
  if oldnames.intersection(p.get('support_objects',[])):
   sign=1 if x>cx+.001 else -1 if x<cx-.001 else 0
   if p['label']=='native_infinigen_dinner_plate':xx=targetx+sign*(.35 if private else .45);yy=cy+(1 if y>cy else -1)*(.23 if private else .26)
   elif p['label']=='native_infinigen_stemmed_glass':xx=targetx+sign*(.55 if private else .68);yy=cy+(1 if y>cy else -1)*(.14 if private else .1508)
   else:xx,yy=targetx,cy
   shift(p,(xx,yy,newtop));p['support_surface_z_m']=newtop;p['support_objects']=new['objects'];props.append(p)
 prop_groups.append((role,targetx,cy,newtop,props,new))
 for n in oldnames:bpy.data.objects.remove(bpy.data.objects[n],do_unlink=True)
inv['products']=[p for p in inv['products'] if p not in tables]
for objs,*rest in templates.values():
 for o in objs:bpy.data.objects.remove(o,do_unlink=True)
bpy.context.view_layer.update();contact_cache={};contacts=[]
for role,cx,cy,top,props,table in prop_groups:
 tree=toptrees[role]
 for p in props:
  asset=p['asset_id'];pos=Vector(p['placement_xyz_m'])
  if asset not in contact_cache:
   pp=[bpy.data.objects[n].matrix_world@v.co for n in p['objects'] for v in bpy.data.objects[n].data.vertices];minz=min(v.z for v in pp);base=[v for v in pp if v.z<=minz+.0003];assert base
   picks=[]
   for a in range(8):
    u=Vector((math.cos(a*math.pi/4),math.sin(a*math.pi/4),0));q=max(base,key=lambda v:(v-pos).dot(u));picks.append(q-pos)
   contact_cache[asset]=picks
  hits=[]
  for rel in contact_cache[asset]:
   q=pos+rel;hit=tree.ray_cast(Vector((q.x-cx,q.y-cy,2)),Vector((0,0,-1)),3)[0];assert hit is not None,('Actual native table top missing under prop foot',role,p['label'],list(q));hits.append(.11+hit.z)
  support=max(hits);assert max(hits)-min(hits)<.002,('Nonplanar native support',p['label'],hits);dz=support-p['placement_xyz_m'][2]
  if abs(dz)>1e-7:shift(p,(pos.x,pos.y,support))
  p['support_surface_z_m']=support;p['floor_support_error_m']=0;contacts.append({'objects':p['objects'],'table_objects':table['objects'],'native_contact_sample_count':len(hits),'actual_table_top_ray_heights_m':hits,'support_z_m':support,'max_contact_plane_deviation_m':max(hits)-min(hits),'pass':True})
for p in rows:
 pp=[bpy.data.objects[n].matrix_world@v.co for n in p['objects'] for v in bpy.data.objects[n].data.vertices];p['saved_mesh_bounds_xyz_m']=[[min(v[k] for v in pp) for k in range(3)],[max(v[k] for v in pp) for k in range(3)]];p['floor_support_error_m']=p['saved_mesh_bounds_xyz_m'][0][2]-.11;assert abs(p['floor_support_error_m'])<1e-4
inv['products']+=rows;inv['scope']+=' r8 true four-seat products replace13oversized2.2m donors:9genuine1.571m Livingston63,945triangle diningtables,4genuine1.37m9,836triangle lightstone/composite tables. No donor rescale; south6seat2.2m native table retained. Native chairs/plates/glasses/centerplants rigidly repositioned at actual table contact heights,8realmesh-foot rays each. Near northWC table center shifted0.1m west. Private lightstone differs from source darkwood and remains explicit visual/acquisition gap.';inv['images']=[preserve_native_packed_image(im) for im in {n.image for m in bpy.data.materials if m.use_nodes for n in m.node_tree.nodes if n.type=='TEX_IMAGE' and n.image}];bpy.ops.wm.save_as_mainfile(filepath=str(out));(W/'native_product_inventory_r8_tables.json').write_text(json.dumps(inv,indent=2));(W/'native_table_prop_contact_rays_r8.json').write_text(json.dumps({'trigger':'Actual northWC approach conflict plus native2.2m table too long for3.25m privatebay side passage','native_source_entries':entries,'native_table_post_generation_rescaling':False,'native_prop_contact_checks':contacts,'pass':all(c['pass'] for c in contacts),'limitations':['Eight actual bottom-foot samples per prop,not continuous contact manifold','Private light stone material is not source dark wood; no photo acceptance','Whole-room full motion/privacy still not approved']},indent=2));(W/'furnished_r8_tables_views.json').write_text((W/'furnished_r7_doors_views.json').read_text());print('FUNCTIONAL_NATIVE_TABLES_SAVED',len(rows),'table products,propsupport',len(contacts),flush=True)
