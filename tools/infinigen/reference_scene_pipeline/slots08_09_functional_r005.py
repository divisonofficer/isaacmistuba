"""Source-reviewed native furnishing: modular native island, actual clothed rail, actual task chair.
Remove visible diagnostic area emitters; use actual native ceiling-light products.
"""
import bpy,json,math,sys,os,traceback
from pathlib import Path
from mathutils import Matrix,Vector
R=Path(__file__).resolve().parents[3];scene=sys.argv[sys.argv.index('--')+1];duplex='duplex'in scene;seed=48712509 if duplex else 48712508;D=R/'data/venue_refs/floor_plans_v3'/scene;B=R/'out/infinigen_v2'/f'kr_{scene}_{seed}/full';src=B/'scene_candidate_r004.blend';out=B/'scene_candidate_r005.blend';assert not out.exists();jp=D/'build_r005_job.json';job={'pid':os.getpid(),'phase':'native_functional_assemblies','source':str(src),'device':'CPU'};jp.write_text(json.dumps(job,indent=2))
def bounds(obs):
 bpy.context.view_layer.update();dg=bpy.context.evaluated_depsgraph_get();ps=[]
 for o in obs:
  if o.type not in ['MESH','CURVE']:continue
  e=o.evaluated_get(dg);m=e.to_mesh();ps.extend(o.matrix_world@v.co for v in m.vertices);e.to_mesh_clear()
 return Vector([min(v[k]for v in ps)for k in range(3)]),Vector([max(v[k]for v in ps)for k in range(3)])
def place(obs,target,angle=0):
 lo,hi=bounds(obs);origin=Vector(((lo.x+hi.x)/2,(lo.y+hi.y)/2,lo.z));M=Matrix.Translation(Vector(target))@Matrix.Rotation(angle,4,'Z')@Matrix.Translation(-origin)
 for o in obs:o.matrix_world=M@o.matrix_world
 return list(hi-lo)
def box(name,loc,dims,mat):
 bpy.ops.mesh.primitive_cube_add(size=1,location=loc);o=bpy.context.object;o.name=name;o.dimensions=dims;bpy.ops.object.transform_apply(location=False,rotation=False,scale=True);o.data.materials.append(mat);m=o.modifiers.new('Actual stone arris','BEVEL');m.width=.006;m.segments=3;return o
try:
 bpy.ops.wm.open_mainfile(filepath=str(src));removed=[]
 for o in list(bpy.context.scene.objects):
  if o.type=='LIGHT'and o.data.type=='AREA':removed.append(o.name);bpy.data.objects.remove(o,do_unlink=True)
 # Native detailed recessed fixtures also serve covered1F galleries/kitchen/study rooms.
 if duplex:
  for o in list(bpy.context.scene.objects):
   if o.name.startswith(tuple('Native_downlight_'+str(i)+'_'for i in [0,1,2,6,7,8])):
    n=o.copy();n.data=o.data.copy()if o.type=='LIGHT'else o.data;bpy.context.scene.collection.objects.link(n);n.name='L0_'+o.name;n.location.z-=3.4
 #3m kitchen island is two original1.495m cabinet products at native scale,with an actual supported stone cap.
 island=[o for o in bpy.context.scene.objects if o.type=='MESH'and o.name.startswith('island_')];floor=0 if duplex else .11;cx,cy=(3.4,6.6)if duplex else(17.1,10);before=place(island,(cx,cy,floor),math.pi/2);copies=[]
 for o in island:n=o.copy();n.data=o.data;bpy.context.scene.collection.objects.link(n);n.name='Island_module_B_'+o.name;n.location.y+=1.505;copies.append(n)
 lo,hi=bounds(island+copies);cap=box('Supported_actual_island_stone_cap',((lo.x+hi.x)/2,(lo.y+hi.y)/2,hi.z+.018),(hi.x-lo.x+.04,hi.y-lo.y+.04,.036),bpy.data.materials['Ivory honed limestone'])
 if duplex:
  for role,target in [('kitchen_unit',(.65,9,0)),('sink_cabinet',(.65,6.4,0)),('oven',(.65,5.2,0))]:place([o for o in bpy.context.scene.objects if o.type=='MESH'and o.name.startswith(role+'_')],target,math.pi/2)
 # Original native chair at desk, independent rigid copy of true sourced chair assembly.
 chair=[o for o in bpy.context.scene.objects if o.type=='MESH'and o.name.startswith('dining_native_chair_0_')];study=[]
 for o in chair:n=o.copy();n.data=o.data;bpy.context.scene.collection.objects.link(n);n.name='Study_native_task_chair_'+o.name;study.append(n)
 place(study,(2.5,.65,0)if duplex else(2.4,9.8,.11))
 # Existing native wardrobe moved clear of gallery/door rather than shrinking to fit.
 wardrobe=[o for o in bpy.context.scene.objects if o.type=='MESH'and o.name.startswith('wardrobe_'if duplex else'Fitted_actual_wardrobe_')]
 wardrobe_dims=place(wardrobe,(2.5,10.5,3.4)if duplex else(8.05,4.3,.11),0 if duplex else math.pi/2)
 # Append exact native cloth/hanger/hook/rail assembly from previous source's actual generated meshes.
 lib=json.loads((R/'data/venue_refs/floor_plans_v3/skyline_penthouse_08/native_library_inventory.json').read_text());names=[n for n in lib['objects']if n.startswith(('FineR36_101_native_shirt_0_','FineR1_101_hanger_0_','FineR1_101_hook_0_'))or n=='FineR1_101_real_hanging_rail_0'];assert len(names)==19,names
 with bpy.data.libraries.load(lib['source'],link=False)as(a,b):b.objects=names.copy()
 obs=b.objects
 for o in obs:bpy.context.scene.collection.objects.link(o)
 bpy.context.view_layer.update()
 for o in obs:M=o.matrix_world.copy();o.parent=None;o.matrix_world=M
 bpy.context.view_layer.update();lo,hi=bounds(obs);native_dims=hi-lo;assert max(native_dims.x,native_dims.y)<2.5,('Do not shrink source clothing assembly',native_dims)
 # Long assembly axis follows westwall,leaving central dressing corridor free.
 angle=math.pi/2 if native_dims.x>native_dims.y else 0;target=(.42,9.25,4.46)if duplex else(6.38,4.3,1.17);place(obs,target,angle)
 for o in obs:o.name='Actual_native_dressing_'+o.name;o['native_clothing_source']=lib['source'];o['rigid_native_dimensions_preserved']=True
 lo,hi=bounds(obs);assert hi.x-lo.x<.9 and hi.y-lo.y<2.5,(lo,hi)
 # Real mounting brackets join source rail to existing westwall;not an invented clothing-product substitute.
 rail=[o for o in obs if 'real_hanging_rail'in o.name][0];rl,rh=bounds([rail]);z=(rl.z+rh.z)/2;wall_x=.11 if duplex else 6.11
 for y in [rl.y+.12,rh.y-.12]:box('Clothes_rail_actual_wall_bracket',((wall_x+target[0])/2,y,z),(abs(target[0]-wall_x),.035,.035),bpy.data.materials['Blackened bronze frames'])
 bpy.context.view_layer.update();bpy.ops.wm.save_as_mainfile(filepath=str(out));views=json.loads((D/'views_r004.json').read_text());(D/'views_r005.json').write_text(json.dumps(views,indent=2));(D/'native_functional_assemblies_r005.json').write_text(json.dumps({'source':str(src),'candidate':str(out),'removed_unphysical_area_emitters':removed,'native_island_module_dimensions_xyz_m':before,'island_assembled_dimensions_xyz_m':list(hi-lo)if False else list(bounds(island+copies)[1]-bounds(island+copies)[0]),'native_wardrobe_original_dimensions_xyz_m':wardrobe_dims,'native_clothing_source':lib['source'],'native_clothing_objects':names,'native_clothing_original_dimensions_xyz_m':list(native_dims),'native_clothing_placed_bounds':[list(lo),list(hi)],'native_clothing_polygon_count':sum(len(o.data.polygons)for o in obs if o.type=='MESH'),'scale_changed':False,'accepted':False,'remaining':'Source sectional shape,pendants,materials,all-roomcamera coverage andfullmesh route/door/support sweeps incomplete'},indent=2));job.update(phase='saved_render_pending',candidate=str(out),exit_code=0)
except BaseException as e:job.update(phase='failed',error=repr(e),traceback=traceback.format_exc(),exit_code=1);raise
finally:jp.write_text(json.dumps(job,indent=2));print(job,flush=True)
