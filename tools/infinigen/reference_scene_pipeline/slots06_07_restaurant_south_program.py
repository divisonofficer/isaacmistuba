import bpy,json,copy
from pathlib import Path
from mathutils import Vector,Matrix
R=Path(__file__).resolve().parents[3];W=R/'out/infinigen_v2/kr_large_restaurant_floor_07_48712507';D=R/'data/venue_refs/floor_plans_v3/large_restaurant_floor_07';src=W/'furnished_r13_portal_skins.blend';out=W/'furnished_r14_south_program.blend';assert not out.exists();bpy.ops.wm.open_mainfile(filepath=str(src));inv=json.loads((W/'native_product_inventory_r13_portal_skins.json').read_text());south=sorted([p for p in inv['products']if p['label']=='native_fullsize_toilet'and p['placement_xyz_m'][1]==4.55],key=lambda p:p['placement_xyz_m'][0]);assert len(south)==3;before={n:bpy.data.objects[n].matrix_world.copy()for p in inv['products']if p not in south for n in p['objects']};moves=[]
def move(p,x):
 dx=x-p['placement_xyz_m'][0]
 for n in p['objects']:o=bpy.data.objects[n];o.matrix_world=Matrix.Translation(Vector((dx,0,0)))@o.matrix_world
 p['placement_xyz_m'][0]=x
 for b in p['saved_mesh_bounds_xyz_m']:b[0]+=dx
 moves.append({'objects':p['objects'],'rigid_translation_m':[dx,0,0],'native_scale_unchanged':True})
for p,x in zip(south,[17.75,18.9,20.05]):move(p,x)
p=copy.deepcopy(south[-1]);p['objects']=[]
for n in south[-1]['objects']:
 old=bpy.data.objects[n];o=old.copy();o.data=old.data;bpy.context.scene.collection.objects.link(o);o.name='South_source_fourth_fullsize_native_'+n;p['objects'].append(o.name)
move(p,21.2);inv['products'].append(p)
removed=[]
for o in list(bpy.data.objects):
 if o.name.startswith('South_WC_route_corrected_partition_'):removed.append(o.name);bpy.data.objects.remove(o,do_unlink=True)
partitions=[];mat=bpy.data.materials['Sanitary_partition_inferred_cream_laminate']
for i,x in enumerate([18.3,19.45,20.6]):
 verts=[(xx,y,z)for z in[.11,2.11]for xx,y in[(x,3.35),(x+.075,3.35),(x+.075,4.89),(x,4.89)]];me=bpy.data.meshes.new('South_WC_route_corrected_partition_source4_'+str(i));me.from_pydata(verts,[],[(0,3,2,1),(4,5,6,7),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)]);me.materials.append(mat);o=bpy.data.objects.new(me.name,me);bpy.context.scene.collection.objects.link(o);partitions.append({'object':o.name,'width_depth_height_m':[.075,1.54,2.0],'front_y_m':3.35,'toilet_center_pitch_m':1.15})
bpy.context.view_layer.update()
for n,M in before.items():assert max(abs(M[i][j]-bpy.data.objects[n].matrix_world[i][j])for i in range(4)for j in range(4))<1e-6
bpy.ops.wm.save_as_mainfile(filepath=str(out));inv['scope']+=' r14 fresh original-reference reinspection corrects earlier mistaken southWCcount3:sourceclearly4toilets/3basins. Rigidlyreposition3genuinefullsizetoilets/addoneexactnativeinstance,3authored75mmpartitionsat1.15m pitch,1.54m depth. No scalingorboxesusedasfurniture. Northenclosedextraceramicregionremainsunresolved.';(W/'native_product_inventory_r14_south_program.json').write_text(json.dumps(inv,indent=2));(W/'body_route_paths_r14_south_program.json').write_text((W/'body_route_paths_r13_portal_skins.json').read_text());views=json.loads((W/'furnished_r13_portal_skins_views.json').read_text());(W/'furnished_r14_south_program_views.json').write_text(json.dumps([v for v in views if v['name']in['overview','south_restroom']],indent=2));(W/'south_source_program_correction_r14.json').write_text(json.dumps({'trigger':'Directoriginalreference reinspection: southWC visibly4toilets,earlier3count was incorrect.','source':str(src),'candidate':str(out),'fixture_program':{'south_wc':{'toilets':4,'basins':3},'north_wc_main_row':{'toilets':4,'basins':2},'single_wc':{'toilets':1,'basins':1}},'source_count_claim_superseded':'source_program_and_fixture_routes_r6_products.json earlier south3 count was erroneous','new_native_toilet_objects':p['objects'],'native_dimensions_xyz_m':p['native_dimensions_xyz_m'],'rigid_moves':moves,'removed_partition_objects':removed,'new_actual_architectural_partitions':partitions,'all_other_native_product_matrices_unchanged':True,'local_render_scope':['overview','south_restroom'],'unaffected_fullscene_render_evidence':'review_r13/frames/render_receipt.json','limits':['Northern extra enclosed ceramic region remains unresolved','Privacy front leaves/hardware still incomplete','No accessibility/source-style/photoreal acceptance'],'acceptance':False},indent=2));c=json.loads((D/'scene_contract.json').read_text());c['current_native_candidate']=str(out.relative_to(R));c['source_uncertainties'].append('Earlier southWC3toiletreading was mistaken:original shows4toilets/3basins.R14corrects native count,retains fullsize fixtures; northern extra enclosed ceramic region still unresolved.');(D/'scene_contract.json').write_text(json.dumps(c,indent=2));print('SOUTH_SOURCE_PROGRAM_CORRECTED_NATIVE4',flush=True)
