"""Physical corrections from saved-mesh r002 audit and actual r001/r002 renders."""
import bpy,json,sys,math,os,traceback
from pathlib import Path
from mathutils import Vector,Matrix
R=Path(__file__).resolve().parents[3];T=Path(__file__).parent;sys.path.insert(0,str(T));from curated_gltf_materials import import_curated_gltf,preserve_native_packed_image
scene=sys.argv[sys.argv.index('--')+1];duplex='duplex'in scene;seed=48712509 if duplex else 48712508;D=R/'data/venue_refs/floor_plans_v3'/scene;B=R/'out/infinigen_v2'/f'kr_{scene}_{seed}/full';src=B/'scene_candidate_r002.blend';out=B/'scene_candidate_r003.blend';assert not out.exists();job={'pid':os.getpid(),'phase':'correcting_saved_mesh_audit','source':str(src),'device':'CPU'};jp=D/'build_r003_job.json'
def state(**kw):job.update(kw);jp.write_text(json.dumps(job,indent=2));print('R003',kw,flush=True)
def box(name,loc,dims,mat):
 bpy.ops.mesh.primitive_cube_add(size=1,location=loc);o=bpy.context.object;o.name=name;o.dimensions=dims;bpy.ops.object.transform_apply(location=False,rotation=False,scale=True);o.data.materials.append(mat);m=o.modifiers.new('Construction arris','BEVEL');m.width=.006;m.segments=3;return o

def partition(name,x,y0,y1,z,doorcenters):
 start=y0
 for i,c in enumerate(doorcenters+[y1+.55]):
  end=min(c-.55,y1)
  if end>start:box(name+str(i),(x,(start+end)/2,z+1.6),(.18,end-start,3.2),wall)
  if c<=y1:box(name+'_door_header'+str(i),(x,c,z+2.85),(.18,1.1,.7),wall)
  start=c+.55

def shift(prefix,delta):
 for o in bpy.context.scene.objects:
  if o.name.startswith(prefix):o.location+=Vector(delta)

state();bpy.ops.wm.open_mainfile(filepath=str(src));wall=bpy.data.materials['Warm lime plaster'];stone=bpy.data.materials['Ivory honed limestone'];glass=bpy.data.materials['Physical 12mm clear glazing IOR1.5'];dark=bpy.data.materials['Blackened bronze frames'];changes=[]
try:
 if duplex:
  # Actual upper terrace slab supports original native bath; ledger/columns are construction evidence,not engineering certification.
  box('L1_terrace_structural_slab',(8,-1.45,3.29),(16,2.9,.22),stone);box('L1_terrace_edge_beam',(8,-2.78,3.13),(16,.18,.28),dark)
  for x in [.13,15.87]:box('L1_terrace_edge_column',(x,-2.78,1.6),(.18,.18,3.2),dark)
  for i in range(8):
   box('L1_terrace_glass_guard'+str(i),(i*2+1,-2.85,3.98),(1.94,.012,1.1),glass);box('L1_terrace_guard_anchor'+str(i),(i*2+.03,-2.85,3.46),(.05,.07,.14),dark)
  # Explicit upstairs side galleries:1m west,1.3m east, shared south/north ring connections.
  for o in list(bpy.context.scene.objects):
   if o.name.startswith(('L1_bed2','L1_master')):bpy.data.objects.remove(o,do_unlink=True)
  for y in [5,7]:box('L1_east_bedroom_partition_'+str(y),(14.15,y,5),(3.7,.18,3.2),wall)
  partition('L1_east_private_wall',12.3,0,14,3.4,[2.5,10])
  partition('L1_west_private_wall',4,0,14,3.4,[2,6.5,9.5,12.5])
  # Existing cross walls must stop at west galleryx4, not block its1m route.
  for o in list(bpy.context.scene.objects):
   if o.name.startswith(('L1_bed3','L1_bath','L1_dress')):bpy.data.objects.remove(o,do_unlink=True)
  for y in [5,8,11]:box('L1_west_room_partition_'+str(y),(2,y,5),(4,.18,3.2),wall)
  # Relocate upper common WC/basin to west bathroom, without changing adult size.
  shift('bathroom_2_adult_toilet',(-4.8,0,0));shift('bathroom_2_pedestal_basin',(-5.8,.8,0))
  # Stair-side gallery edge is an anchored glass guard, clear at north landing.
  box('L1_east_gallery_void_guard',(11.03,7,3.95),(.012,8,1.1),glass)
  for y in [3.2,5.2,7.2,9.2,10.8]:box('L1_east_gallery_guard_shoe',(11.03,y,3.46),(.08,.06,.12),dark)
  changes+=['Upper terrace bath supported by new3.4m slab/beam/columns and guard','Upper east/west independent galleries and bedroom/bath partitions created','Upper WC/basin relocated into west bathroom']
 else:
  # Saved native floor surfaces are atZ0.110m,confirmed actual evaluated triangle audit.
  moved=[]
  for o in bpy.context.scene.objects:
   if o.type!='MESH':continue
   if o.get('native_product_id') or o.name=='Actual_native_dining_table':
    pts=[o.matrix_world@Vector(v) for v in o.bound_box];cy=sum(p.y for p in pts)/8
    if cy>0:o.location.z+=.11;moved.append(o.name)
  # Remove native louvers/window assemblies remaining at perimeter,including randomized factory leaf meshes.
  hidden=[]
  for o in bpy.context.scene.objects:
   if o.type!='MESH' or o.get('native_product_id') or o.get('architecture_construction'):continue
   pts=[o.matrix_world@Vector(v) for v in o.bound_box];lo=min(p.y for p in pts);hi=max(p.y for p in pts)
   if (hi<.45 or lo>13.55) and not o.name.endswith(('.floor','.ceiling','.wall')):o.hide_render=True;hidden.append(o.name)
  # Correct source product toilet/tub overlap while preserving all original product dimensions.
  shift('bathroom_0_adult_toilet',(-.4,1,0));shift('bathroom_0_pedestal_basin',(-.25,1,0))
  # Author actual north living terrace and framed guard,matching reference orientation.
  box('North_terrace_structural_slab',(11.5,15.45,-.03),(23,2.9,.28),stone)
  for i in range(12):box('North_terrace_glass_guard'+str(i),(i*2+1,16.85,.69),(1.94,.012,1.1),glass);box('North_terrace_post'+str(i),(i*2+.03,16.85,.69),(.035,.035,1.16),dark)
  # Place actual native terrace trees/tables/chairs by rigid duplication preserving mesh+UV,not invented primitive props.
  originals=[o for o in bpy.context.scene.objects if o.type=='MESH' and o.name.startswith(('terrace_chair','terrace_side_table'))]
  for o in originals:n=o.copy();n.data=o.data;bpy.context.scene.collection.objects.link(n);n.name='North_'+o.name;n.location.y+=16.9;n.location.z+=.11
  for o in list(bpy.context.scene.objects):
   if o.name.startswith('native_olive_tree_') and o.type=='MESH' and o.location.y>10:
    n=o.copy();n.data=o.data;bpy.context.scene.collection.objects.link(n);n.name='North_terrace_'+o.name;n.location.y+=2.3
  changes+=['Actual penthouse floorZ0.110m corrected for all indoor native products','Original perimeter louver/window assemblies hidden after fullheight glass correction','North living terrace constructed and furnished with actual native product copies','Master toilet/basin separated from tub']
  (D/'physical_correction_r003_details.json').write_text(json.dumps({'moved_floor_contact_meshes':moved,'hidden_perimeter_assemblies':hidden},indent=2))
 # Direct panorama review found reflected unsupported area-light discs.
 # Suppress diagnostic emitter visibility and integrate native Infinigen downlights.
 for o in bpy.context.scene.objects:
  if o.type=='LIGHT' and o.data.type=='AREA':
   o.visible_glossy=False;o.visible_camera=False;o.data.energy*=.25
 native=R/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03/native_downlight_pilot';scope=json.loads((native/'scope.json').read_text())
 with bpy.data.libraries.load(scope['source'],link=False) as (a,b):b.objects=[scope['object']]+scope['native_children']
 original=b.objects
 for o in original:bpy.context.scene.collection.objects.link(o)
 bpy.context.view_layer.update()
 poses={o:o.matrix_world.copy() for o in original}
 for o in original:o.parent=None;o.matrix_world=poses[o]
 for idx,(x,y) in enumerate([(x,y) for x in ([3,7,13] if duplex else [3,7,12,18,21]) for y in [2,7,12]]):
  z=6.58 if duplex else 3.08
  for o in original:
   n=o.copy();n.data=o.data.copy() if o.type=='LIGHT' else o.data;bpy.context.scene.collection.objects.link(n);n.name='Native_downlight_'+str(idx)+'_'+o.name;n.matrix_world=Matrix.Translation(Vector((x,y,z)))@poses[o];n['native_fixture_factory']=scope['factory'];n['native_fixture_seed']=scope['seed']
 for o in original:bpy.data.objects.remove(o,do_unlink=True)
 if not duplex:
  # Original388poly2.71m wardrobe physically exceeded2.5m dressing room width.
  for o in list(bpy.context.scene.objects):
   if o.name.startswith('wardrobe_'):bpy.data.objects.remove(o,do_unlink=True)
  entry=json.loads((D/'compact_wardrobe_r003.json').read_text());new,meshes,profile=import_curated_gltf(entry,repair_nonpositive_ior=1.5);bpy.context.view_layer.update()
  for o in new:M=o.matrix_world.copy();o.parent=None;o.matrix_world=M
  bpy.context.view_layer.update();ps=[o.matrix_world@v.co for o in meshes for v in o.data.vertices];lo=Vector([min(v[k] for v in ps)for k in range(3)]);hi=Vector([max(v[k] for v in ps)for k in range(3)]);expected=entry['declared_native_dimensions_xyz_m'];assert max(abs(a-b)for a,b in zip(hi-lo,expected))<.01
  M=Matrix.Translation(Vector((7.3,4.4,.11)))@Matrix.Translation(Vector((-(lo.x+hi.x)/2,-(lo.y+hi.y)/2,-lo.z)))
  for o in new:o.matrix_world=M@o.matrix_world;o.name='Fitted_actual_wardrobe_'+o.name;o['native_product_id']=entry['id'];o['unit_scale_preserved']=True
  changes.append('Oversize wardrobe replaced by actual1.02m native Olivia wardrobe without rescaling; walk-in clothing still unresolved')
 for im in bpy.data.images:
  if im.source=='FILE' and min(im.size)>0:
   try:preserve_native_packed_image(im)
   except Exception:pass
 # Mirror the SAME authored skyline architecture across apartment for north-facing continuity.
 for o in list(bpy.context.scene.objects):
  if o.name.startswith(('City_building','City_facade_band')):
   n=o.copy();n.data=o.data;bpy.context.scene.collection.objects.link(n);n.name='North_'+o.name;n.location.y=28-o.location.y
 bpy.context.view_layer.update();bpy.ops.wm.save_as_mainfile(filepath=str(out));views=json.loads((D/'views_r002.json').read_text());views[-1]['location']=[8,8.8,1.65] if duplex else [11,12,1.65];(D/'views_r003.json').write_text(json.dumps(views,indent=2));(D/'physical_correction_r003.json').write_text(json.dumps({'source':str(src),'candidate':str(out),'changes':changes,'accepted':False,'remaining':['True sliding/operable terrace door routes not yet validated','Native wardrobe fit/detail and source walk-in clothing unresolved','Stair/guard engineering certification absent; construction geometry only','All-room high-resolution source matching and micro materials incomplete']},indent=2));state(phase='saved_render_pending',candidate=str(out),exit_code=0)
except BaseException as e:state(phase='failed',error=repr(e),traceback=traceback.format_exc(),exit_code=1);raise
