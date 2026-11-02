"""Native mesh first furnished candidates. No furniture proxy generation."""
import bpy,json,math,sys,hashlib
from pathlib import Path
from mathutils import Vector,Matrix
T=Path(__file__).parent;R=T.parents[2];sys.path.insert(0,str(T))
from curated_gltf_materials import import_curated_gltf,preserve_native_packed_image
scene=sys.argv[sys.argv.index('--')+1];seed=48712506 if 'workshop' in scene else 48712507
D=R/'data/venue_refs/floor_plans_v3'/scene;W=R/'out/infinigen_v2'/f'kr_{scene}_{seed}';out=W/'furnished_r1.blend';assert not out.exists();bpy.ops.wm.open_mainfile(filepath=str(W/'full/scene.blend'));rows=[];templates={}
floor=.11
# Load every actual native mesh before detaching parent transforms.
def get(e):
 if e['id'] in templates:return templates[e['id']]
 new,objs,profile=import_curated_gltf(e,repair_nonpositive_ior=1.5);bpy.context.view_layer.update();matrices={o:o.matrix_world.copy() for o in objs}
 for o in objs:o.parent=None;o.matrix_world=matrices[o]
 for o in new:
  if o.type!='MESH':bpy.data.objects.remove(o,do_unlink=True)
 bpy.context.view_layer.update();pts=[o.matrix_world@v.co for o in objs for v in o.data.vertices];lo=Vector([min(v[k] for v in pts) for k in range(3)]);hi=Vector([max(v[k] for v in pts) for k in range(3)]);dims=hi-lo
 assert .1<dims.z<3.0,(e['id'],list(dims))
 mats={o:o.matrix_world.copy() for o in objs};templates[e['id']]=(objs,mats,lo,hi,profile);return templates[e['id']]
def place(e,x,y,angle=0,label='product'):
 objs,mats,lo,hi,profile=get(e);center=Vector(((lo.x+hi.x)/2,(lo.y+hi.y)/2,lo.z));M=Matrix.Translation((x,y,floor))@Matrix.Rotation(angle,4,'Z')@Matrix.Translation(-center);copies=[]
 for src in objs:
  o=src.copy();o.data=src.data;bpy.context.scene.collection.objects.link(o);o.matrix_world=M@mats[src];o.name=f'{label}_{len(rows):03d}_{src.name}';o['native_asset_id']=e['id'];copies.append(o)
 rows.append({'label':label,'asset_id':e['id'],'source':e['path'],'sha256':e.get('copied_sha256'),'native_dimensions_xyz_m':list(hi-lo),'native_scale_preserved':True,'placement_xyz_m':[x,y,floor],'yaw_radians':angle,'polygons':sum(len(o.data.polygons) for o in copies),'objects':[o.name for o in copies],'material_profile':profile})
if seed==48712506:
 es=json.loads((D/'native_products/asset_manifest.json').read_text())['assets'];bench,vise,drill,cab=es
 for room,positions in {
 'west_main':[(1.4,9),(1.4,12),(1.4,15.5),(4.5,12.8),(4.5,9.5)],
 'central_main':[(8.3,11),(8.3,14.5),(10.5,12.8),(10.5,16)],
 'east_main':[(13.5,15.5),(16,15.5),(16.8,12),(14,9.5)],
 'southwest':[(1.5,2),(1.5,5),(4.8,3)],
 'southcentral':[(8.4,2),(10.5,3.8)],
 'southeast':[(13.8,2),(16.5,3.5),(14,5.5)]}.items():
  for i,(x,y) in enumerate(positions):place(vise if i%3==0 else bench,x,y,math.pi/2 if i%2 else 0,label=room+'_native_workbench')
 for x,y in [(3,16),(5.7,15.8),(9.4,16),(13.5,16),(17,8),(5.5,5.5),(10,1),(16.8,1.4)]:place(drill,x,y,label='native_drill_press')
 for x,y in [(6,10),(6,13),(1.3,16),(11,10),(13,12),(17,14),(6,1.3),(11,5),(13,1),(17,6)]:place(cab,x,y,label='native_industrial_cabinet')
 views=[{'name':'overview','location':[9,8.5,32],'target':[9,8.5,0],'overview':True,'ortho_scale':23,'render_width':960,'samples':32},{'name':'west_workshop','location':[6.3,8.4,1.7],'target':[2,14,.9],'hfov':72,'render_width':768},{'name':'east_workshop','location':[12.8,8.5,1.7],'target':[16,14,.9],'hfov':72,'render_width':768}]
else:
 tables=json.loads((R/'data/venue_refs/floor_plans_v3/commercial_office_floor_02/real_table_candidates/asset_manifest.json').read_text())['assets'];chairs=json.loads((R/'data/venue_refs/floor_plans_v3/commercial_office_floor_02/real_chair_candidates/asset_candidates_manifest.json').read_text())['assets'];table=tables[0];chair=chairs[0]
 for x,y in [(10.4,7.2),(14.3,7.2),(18,7.2),(10.4,10.7),(14.3,10.7),(18,10.7),(10.4,13.6),(14.3,13.6),(17.7,13.6),(7.625,16.5),(10.875,16.5),(14.125,16.5),(17.375,16.5),(4.5,2)]:
  place(table,x,y,label='native_dining_table')
  for xx in [-.65,.65]:
   place(chair,x+xx,y-.85,0,label='native_dining_chair');place(chair,x+xx,y+.85,math.pi,label='native_dining_chair')
 views=[{'name':'overview','location':[11,9,35],'target':[11,9,0],'overview':True,'ortho_scale':27,'render_width':960,'samples':32},{'name':'main_dining','location':[7.5,6,1.65],'target':[15,12,1.0],'hfov':74,'render_width':768},{'name':'private_booth','location':[7.6,15.2,1.6],'target':[7.6,17.3,.8],'hfov':80,'render_width':768}]
# Remove library templates only; native copies share unchanged geometry/materials.
for objs,*rest in templates.values():
 for o in objs:bpy.data.objects.remove(o,do_unlink=True)
# Physically neutral inferred supplementary lighting, no furniture represented by lights.
for ix,x in enumerate([3,8,13,18]):
 for iy,y in enumerate([3,8,13,16]):
  ld=bpy.data.lights.new(f'Authored_fill_{ix}_{iy}','AREA');ld.energy=180;ld.shape='DISK';ld.size=3;o=bpy.data.objects.new(ld.name,ld);bpy.context.scene.collection.objects.link(o);o.location=(x,y,3.0)
world=bpy.context.scene.world
if world and world.use_nodes:world.node_tree.nodes.get('Background').inputs['Strength'].default_value=.3
bpy.context.view_layer.update();images=[]
for im in {n.image for m in bpy.data.materials if m.use_nodes for n in m.node_tree.nodes if n.type=='TEX_IMAGE' and n.image}:images.append(preserve_native_packed_image(im))
# Evaluate floor support and geometry bounds of actual placed meshes, not metadata boxes.
for row in rows:
 obs=[bpy.data.objects[n] for n in row['objects']];pts=[o.matrix_world@v.co for o in obs for v in o.data.vertices];lo=[min(v[k] for v in pts) for k in range(3)];hi=[max(v[k] for v in pts) for k in range(3)];row['saved_mesh_bounds_xyz_m']=[lo,hi];row['floor_support_error_m']=lo[2]-floor;assert abs(row['floor_support_error_m'])<1e-4
bpy.ops.wm.save_as_mainfile(filepath=str(out));(W/'furnished_r1_views.json').write_text(json.dumps(views,indent=2));(W/'native_product_inventory_r1.json').write_text(json.dumps({'products':rows,'images':images,'scope':'Real native product geometry and UV preserved; native-scale placement. Constant invalid IOR corrected explicitly to inferred1.5. No claim of surveyed dimensions, final clearance, reference acceptance, or photorealism.','photorealism_accepted':False},indent=2));print('FURNISHED_R1_SAVED',scene,len(rows),flush=True)
