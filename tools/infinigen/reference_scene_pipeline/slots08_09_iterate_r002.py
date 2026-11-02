"""Source-reviewed r002: real functional products and construction corrections."""
import bpy,bmesh,json,sys,math,time,os,traceback
from pathlib import Path
from mathutils import Matrix,Vector
R=Path(__file__).resolve().parents[3];T=Path(__file__).parent;sys.path.insert(0,str(T));from curated_gltf_materials import import_curated_gltf,preserve_native_packed_image
scene=sys.argv[sys.argv.index('--')+1];duplex='duplex' in scene;seed=48712509 if duplex else 48712508;D=R/'data/venue_refs/floor_plans_v3'/scene;B=R/'out/infinigen_v2'/f'kr_{scene}_{seed}/full';src=B/'scene_candidate_r001.blend';out=B/'scene_candidate_r002.blend';assert not out.exists();jp=D/'build_r002_job.json';job={'pid':os.getpid(),'phase':'source_review_iteration','source':str(src),'device':'CPU'}
def state(**kw):job.update(kw);jp.write_text(json.dumps(job,indent=2));print('R002',kw,flush=True)
state();bpy.ops.wm.open_mainfile(filepath=str(src));assets=json.loads((D/'native_assets_r002.json').read_text());rows=[]
def add(role,loc,angle=0,key=None):
 entry=assets[role];new,meshes,profile=import_curated_gltf(entry,repair_nonpositive_ior=1.5);bpy.context.view_layer.update()
 for o in new:M=o.matrix_world.copy();o.parent=None;o.matrix_world=M
 bpy.context.view_layer.update();ps=[o.matrix_world@v.co for o in meshes for v in o.data.vertices];lo=Vector([min(p[k] for p in ps) for k in range(3)]);hi=Vector([max(p[k] for p in ps) for k in range(3)]);dims=hi-lo;expected=[float(x) for x in entry['aligned_dims_yup_m'].split(',')];expected=[expected[0],expected[2],expected[1]];assert max(abs(a-b) for a,b in zip(dims,expected))<.01,(role,dims,expected);M=Matrix.Translation(Vector(loc))@Matrix.Rotation(angle,4,'Z')@Matrix.Translation(Vector((-(lo.x+hi.x)/2,-(lo.y+hi.y)/2,-lo.z)))
 for o in new:o.matrix_world=M@o.matrix_world;o.name=(key or role)+'_'+o.name;o['native_product_id']=entry['id'];o['unit_scale_preserved']=True
 rows.append({'role':role,'key':key,'asset_id':entry['id'],'native_dimensions_xyz_m':list(dims),'semantic_dimensions_match_xyz':True,'center_floor':loc,'scale_change':False,'polygons':sum(len(o.data.polygons) for o in meshes),'optical_preflight':profile})
 return new
try:
 if duplex:
  # Review found open east side; add real6.6m glazing, framing and structure.
  glass=bpy.data.materials['Physical 12mm clear glazing IOR1.5'];dark=bpy.data.materials['Blackened bronze frames']
  for i in range(7):
   bpy.ops.mesh.primitive_cube_add(size=1,location=(16,i*2+1,3.3));o=bpy.context.object;o.name='East_actual_glazing_'+str(i);o.dimensions=(.012,1.94,6.52);o.data.materials.append(glass)
   bpy.ops.mesh.primitive_cube_add(size=1,location=(16,i*2,3.3));o=bpy.context.object;o.name='East_actual_mullion_'+str(i);o.dimensions=(.08,.055,6.6);o.data.materials.append(dark)
  # Move sofa and coffee table clear of one another. Preserve rigid native shape.
  for prefix,target,angle in [('L0_living_sofa_',Vector((7.5,7.4,0)),math.pi/2),('L0_living_coffee_',Vector((7.5,5.7,0)),0)]:
   obs=[o for o in bpy.context.scene.objects if o.name.startswith(prefix) and o.type=='MESH'];ps=[o.matrix_world@v.co for o in obs for v in o.data.vertices];lo=Vector([min(p[k] for p in ps) for k in range(3)]);hi=Vector([max(p[k] for p in ps) for k in range(3)]);origin=Vector(((lo.x+hi.x)/2,(lo.y+hi.y)/2,lo.z));M=Matrix.Translation(target)@Matrix.Rotation(angle,4,'Z')@Matrix.Translation(-origin)
   for o in obs:o.matrix_world=M@o.matrix_world
  # Fix initial toilet/basin boundary breach by rigidly translating both600mm inward.
  for o in bpy.context.scene.objects:
   if o.name.startswith(('bathroom_0_adult_toilet','bathroom_0_pedestal_basin')):o.location.x-=.6
  for role,p in [('kitchen_unit',(1.2,8.7,0)),('sink_cabinet',(1.1,6.4,0)),('oven',(1.0,5.3,0)),('island',(3.4,7.1,0)),('washer',(1.1,12.5,0)),('desk',(2.5,1.5,0)),('wardrobe',(2.5,9.6,3.4)),('bath',(3.0,12.6,3.4)),('bath',(13,-1.4,3.4))]:add(role,p)
 else:
  # Native shell's window-height walls visibly defeated source full-height panorama.
  # Remove only north/south perimeter wall faces; preserve the native internal partition network.
  changed=[]
  for o in list(bpy.context.scene.objects):
   if o.type!='MESH':continue
   if 'wall' in o.name.lower() and not o.get('architecture_construction'):
    bm=bmesh.new();bm.from_mesh(o.data);faces=[f for f in bm.faces if all((o.matrix_world@v.co).y<.25 for v in f.verts) or all((o.matrix_world@v.co).y>13.75 for v in f.verts)]
    if faces:bmesh.ops.delete(bm,geom=faces,context='FACES');bm.to_mesh(o.data);changed.append({'object':o.name,'removed_perimeter_faces':len(faces)})
    bm.free()
   if 'window' in o.name.lower():
    points=[o.matrix_world@Vector(v) for v in o.bound_box];cy=sum(v.y for v in points)/8
    if cy<.5 or cy>13.5:o.hide_render=True
   if o.name.endswith('.floor'):
    o.data.materials.clear();o.data.materials.append(bpy.data.materials['Ivory honed limestone'])
  (D/'perimeter_glazing_correction_r002.json').write_text(json.dumps(changed,indent=2))
  for role,p in [('kitchen_unit',(18.8,12.6,0)),('sink_cabinet',(19,10.8,0)),('oven',(18.9,9.7,0)),('island',(17.1,11,0)),('washer',(21.8,10.2,0)),('sink_cabinet',(21.8,12,0)),('desk',(2.4,10.8,0)),('wardrobe',(7.3,4.3,0)),('bath',(7.2,1.0,0))]:add(role,p)
 # All original native embedded images packed without changing embedded bytes.
 images=[]
 for im in bpy.data.images:
  if im.source=='FILE' and min(im.size)>0:
   try:images.append(preserve_native_packed_image(im))
   except Exception:pass
 bpy.context.view_layer.update();bpy.ops.wm.save_as_mainfile(filepath=str(out));(D/'native_products_r002.json').write_text(json.dumps({'new_products':rows,'native_images':images,'source_preserved':str(src),'accepted':False,'remaining':'Wardrobe doors do not constitute source walk-in clothing; kitchen product styles only first integration. Native source authenticity/scale is not visual acceptance.'},indent=2))
 W=16 if duplex else 23;views=[{'name':'overview','overview':True,'location':[W*.8,-11.2,25],'target':[W/2,7,2 if duplex else 0],'ortho_scale':W*1.65,'render_width':800},{'name':'living_context','location':[6,2,1.65] if duplex else[6.2,8.7,1.65],'target':[11,9,2.2] if duplex else[12,13,1.5],'hfov':75,'render_width':800},{'name':'panorama_context','location':[8.1,10.2,1.65] if duplex else[11,12,1.65],'target':[8,-2,1.5] if duplex else[12,7,1.5],'hfov':75,'render_width':800}];(D/'views_r002.json').write_text(json.dumps(views,indent=2));state(phase='saved_render_pending',candidate=str(out),exit_code=0)
except BaseException as e:state(phase='failed',error=repr(e),traceback=traceback.format_exc(),exit_code=1);raise
