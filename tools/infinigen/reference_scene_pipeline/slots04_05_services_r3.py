import bpy,json,math,sys
from pathlib import Path
from mathutils import Vector,Matrix
T=Path(__file__).parent;sys.path.insert(0,str(T));from curated_gltf_materials import import_curated_gltf,preserve_native_packed_image
R=T.parents[2]
def load(ref,file,i=0):return json.loads((R/'data/venue_refs/floor_plans_v3'/ref/file).read_text())['assets'][i]
def place(e,xy,angle=0,role=''):
 new,objs,profile=import_curated_gltf(e,repair_nonpositive_ior=1.5);bpy.context.view_layer.update();m={o:o.matrix_world.copy() for o in objs}
 for o in objs:o.parent=None;o.matrix_world=m[o]
 rot=Matrix.Rotation(angle,4,'Z')
 for o in objs:o.matrix_world=rot@o.matrix_world
 bpy.context.view_layer.update();pts=[o.matrix_world@v.co for o in objs for v in o.data.vertices];lo=Vector([min(v[k] for v in pts) for k in range(3)]);hi=Vector([max(v[k] for v in pts) for k in range(3)]);dim=hi-lo;assert all(.05<x<5 for x in dim),list(dim)
 delta=Vector((xy[0]-(hi.x+lo.x)/2,xy[1]-(hi.y+lo.y)/2,.025-lo.z))
 for o in objs:o.location+=delta;o['reference_role']=role;o['source_asset_id']=e['id']
 rows.append({'id':e['id'],'name':e.get('name'),'role':role,'dimensions_m':list(dim),'position_xy':xy,'rotation_rad':angle,'scale_policy':'native unchanged','triangles':sum(len(o.data.polygons) for o in objs),'material_profile':profile})
 return dim

services=json.loads((R/'data/venue_refs/floor_plans_v3/shared_dining_residence_05/native_service_products_manifest.json').read_text())['assets'];wash,cab,sink,hob,fridge=services
for scene,seed,slot in [('rural_stone_cottage_04',48712504,'04'),('shared_dining_residence_05',48712505,'05')]:
 D=R/'data/venue_refs/floor_plans_v3'/scene;W=R/'out/infinigen_v2'/f'kr_{scene}_{seed}'/'full';src=W/f'scene_candidate_slots{slot}_r2.blend';out=W/f'scene_candidate_slots{slot}_r3.blend';assert not out.exists();bpy.ops.wm.open_mainfile(filepath=str(src));rows=[]
 if slot=='05':
  for e,x in [(cab,7.4),(sink,8.1),(cab,8.8),(hob,9.5),(cab,10.1),(fridge,11.0)]:place(e,(x,10.25),0,'main_native_kitchen')
  place(wash,(3.65,.55),math.pi,'native_washing_machine');place(sink,(4.65,.55),math.pi,'native_utility_sink');place(fridge,(7.6,1.2),math.pi,'utility_refrigerator')
  wc=load('dual_unit_residential_floor_03','sanitary106_complete_products/asset_manifest.json',3);place(wc,(2.25,1.0),math.pi/2,'adult_native_wc_pan')
 else:
  for e,y in [(cab,7.3),(sink,8.1),(hob,8.9),(cab,9.6)]:place(e,(9.7,y),-math.pi/2,'main_kitchen_native_products_provisional_modern_style')
  for e,y in [(cab,3.4),(sink,4.2),(hob,5.0)]:place(e,(13.05,y),-math.pi/2,'aux_kitchen_native_products_provisional_modern_style')
 packed=[preserve_native_packed_image(im) for im in {n.image for m in bpy.data.materials if m.use_nodes for n in m.node_tree.nodes if n.type=='TEX_IMAGE' and n.image}]
 bpy.ops.wm.save_as_mainfile(filepath=str(out));(D/'candidate_r3_service_inventory.json').write_text(json.dumps({'candidate':str(out),'source':str(src),'assets':rows,'packed_images':packed,'limitations':['Native modern service products retain actual dimensions; cottage style mismatch remains','Cabinet adjacency, fronts, support, route clearance and plumbing require saved mesh and render inspection','Furniture/native optical constants inferred; no photorealism acceptance'],'photorealism_accepted':False},indent=2));print('SERVICE_R3_SAVED',scene,flush=True)
