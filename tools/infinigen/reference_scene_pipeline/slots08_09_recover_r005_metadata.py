"""Recover post-save JSON serialization failure without regenerating/changing saved candidate."""
import bpy,json,sys,hashlib,os,traceback,shutil
from pathlib import Path
from mathutils import Vector
R=Path(__file__).resolve().parents[3];scene=sys.argv[sys.argv.index('--')+1];duplex='duplex'in scene;seed=48712509 if duplex else 48712508;D=R/'data/venue_refs/floor_plans_v3'/scene;P=R/'out/infinigen_v2'/f'kr_{scene}_{seed}/full/scene_candidate_r005.blend';jp=D/'build_r005_job.json';shutil.copy2(jp,D/'build_r005_attempt2_postsave_json_failure.json');sha=hashlib.sha256(P.read_bytes()).hexdigest();job={'pid':os.getpid(),'phase':'verifying_saved_candidate_metadata_recovery','source':str(P),'device':'CPU','original_postsave_failure':'JSON objects list mutated by Blender library loader;candidate saved before metadata failure'};jp.write_text(json.dumps(job,indent=2))
def bounds(obs):
 bpy.context.view_layer.update();dg=bpy.context.evaluated_depsgraph_get();ps=[]
 for o in obs:
  if o.type not in['MESH','CURVE']:continue
  e=o.evaluated_get(dg);m=e.to_mesh();ps.extend(o.matrix_world@v.co for v in m.vertices);e.to_mesh_clear()
 lo=Vector([min(p[k]for p in ps)for k in range(3)]);hi=Vector([max(p[k]for p in ps)for k in range(3)]);return lo,hi
try:
 bpy.ops.wm.open_mainfile(filepath=str(P));actual=[o for o in bpy.context.scene.objects if o.name.startswith('Actual_native_dressing_')];assert len(actual)==19;lo,hi=bounds(actual);actual_dims=hi-lo;island=[o for o in bpy.context.scene.objects if o.name.startswith(('island_','Island_module_B_'))];il,ih=bounds(island);removed=not any(o.type=='LIGHT'and o.data.type=='AREA'for o in bpy.context.scene.objects);assert removed
 lib=json.loads((R/'data/venue_refs/floor_plans_v3/skyline_penthouse_08/native_library_inventory.json').read_text());names=[n for n in lib['objects']if n.startswith(('FineR36_101_native_shirt_0_','FineR1_101_hanger_0_','FineR1_101_hook_0_'))or n=='FineR1_101_real_hanging_rail_0'];assert len(names)==19
 with bpy.data.libraries.load(lib['source'],link=False)as(a,b):b.objects=names.copy()
 original=b.objects
 for o in original:bpy.context.scene.collection.objects.link(o)
 bpy.context.view_layer.update()
 for o in original:M=o.matrix_world.copy();o.parent=None;o.matrix_world=M
 nl,nh=bounds(original);native_dims=nh-nl;assert abs(native_dims.z-actual_dims.z)<.001;assert max(abs(a-b)for a,b in zip(sorted(native_dims[:2]),sorted(actual_dims[:2])))<.001
 data={'source_candidate':str(P),'source_sha256':sha,'native_clothing_source':lib['source'],'native_clothing_objects':names,'native_clothing_original_dimensions_xyz_m':list(native_dims),'native_clothing_placed_dimensions_xyz_m':list(actual_dims),'actual_clothing_bounds_xyz_m':[list(lo),list(hi)],'all3_dimensions_match_under_rigid90degree_rotation':True,'native_clothing_mesh_polygons':sum(len(o.data.polygons)for o in actual if o.type=='MESH'),'actual_island_assembly_dimensions_xyz_m':list(ih-il),'native_island_module_scale_changed':False,'all_unphysical_area_lights_removed':removed,'source_blend_unchanged':hashlib.sha256(P.read_bytes()).hexdigest()==sha,'accepted':False,'remaining':['Full source sectional/finish/pendant matching incomplete','All-roomcamera/doorroute/fullmeshcollision validation incomplete','Native clothes preserve original source assembly;new room mounting/supportneeds close review']};(D/'native_functional_assemblies_r005.json').write_text(json.dumps(data,indent=2));views=json.loads((D/'views_r005.json').read_text())
 if not duplex:views[-1].update(name='kitchen_panorama_context',location=[18.2,8.6,1.65],target=[13,12.5,1.5])
 (D/'views_r005.json').write_text(json.dumps(views,indent=2));job.update(phase='saved_verified_render_pending',candidate=str(P),candidate_sha256=sha,exit_code=0,metadata_recovered_without_blend_edits=True)
except BaseException as e:job.update(phase='failed',error=repr(e),traceback=traceback.format_exc(),exit_code=1);raise
finally:jp.write_text(json.dumps(job,indent=2));print(job,flush=True)
