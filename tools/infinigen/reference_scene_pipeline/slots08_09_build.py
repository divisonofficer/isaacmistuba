"""First two-level reference candidate and native product furnishing.
Architecture consists of real slabs, wall panels, glazing, mullions, steps, stringers
and anchored guards. No furniture proxy meshes. All products are appended native
high-detail source assets at rigid unit scale, preserving UV/materials.
"""
import bpy,sys,json,math,os,time,hashlib,random,traceback
from pathlib import Path
from mathutils import Vector,Matrix
R=Path(__file__).resolve().parents[3];T=Path(__file__).parent;REF=R/'data/venue_refs/floor_plans_v3';SRC=REF/'dual_unit_residential_floor_03';scene=sys.argv[sys.argv.index('--')+1];D=REF/scene;duplex='duplex' in scene;seed=48712509 if duplex else 48712508;B=R/'out/infinigen_v2'/f'kr_{scene}_{seed}'/'full';B.mkdir(parents=True,exist_ok=True);out=B/'scene_candidate_r001.blend';assert not out.exists();job={'pid':os.getpid(),'phase':'building','device':'CPU','started_unix':time.time(),'scene_id':scene};jp=D/'build_r001_job.json'
def state(**kw):job.update(kw);jp.write_text(json.dumps(job,indent=2));print('SLOTS_BUILD',kw,flush=True)
def mat(name,color,rough=.4,metal=0,glass=False,stone=False):
 m=bpy.data.materials.new(name);m.diffuse_color=(*color,1);m.use_nodes=True;n=m.node_tree.nodes;bs=n.get('Principled BSDF');bs.inputs['Base Color'].default_value=(*color,1);bs.inputs['Roughness'].default_value=rough;bs.inputs['Metallic'].default_value=metal;bs.inputs['IOR'].default_value=1.5
 if glass:bs.inputs['Transmission Weight'].default_value=1;bs.inputs['Roughness'].default_value=.025
 if stone:
  tex=n.new('ShaderNodeTexNoise');tex.inputs['Scale'].default_value=2.8;tex.inputs['Detail'].default_value=4;coord=n.new('ShaderNodeTexCoord');m.node_tree.links.new(coord.outputs['Generated'],tex.inputs['Vector']);bump=n.new('ShaderNodeBump');bump.inputs['Strength'].default_value=.12;bump.inputs['Distance'].default_value=.012;m.node_tree.links.new(tex.outputs['Fac'],bump.inputs['Height']);m.node_tree.links.new(bump.outputs['Normal'],bs.inputs['Normal'])
 return m

def box(name,loc,dims,material,bevel=.012):
 bpy.ops.mesh.primitive_cube_add(size=1,location=loc);o=bpy.context.object;o.name=name;o.dimensions=dims;bpy.ops.object.transform_apply(location=False,rotation=False,scale=True);o.data.materials.append(material)
 if bevel:
  m=o.modifiers.new('Actual edge arris','BEVEL');m.width=bevel;m.segments=3;o.modifiers.new('Weighted construction normals','WEIGHTED_NORMAL')
 o['architecture_construction']=True;return o

def beam(name,a,b,width,material):
 a,b=Vector(a),Vector(b);o=box(name,(a+b)/2,(width,width,(b-a).length),material,.005);o.rotation_euler=(b-a).to_track_quat('Z','Y').to_euler();return o

def walls(name,x0,y0,x1,y1,z=0,h=3.2,doors=None):
 # Source internal partition segment; omit explicit 1.1m opening and add real lintel.
 if abs(x1-x0)<.01:axis=1;start,end=y0,y1
 else:axis=0;start,end=x0,x1
 cuts=[(start,end)]
 if doors:
  c=doors;cuts=[(start,c-.55),(c+.55,end)]
  loc=((x0,y0+c*0,z) if False else (x0,c,z+h-.35)) if axis else (c,y0,z+h-.35)
  box(name+'_door_lintel',loc,(.22,1.1,.7) if axis else (1.1,.22,.7),wall)
 for i,(a,b) in enumerate(cuts):
  if b-a<.02:continue
  loc=(x0,(a+b)/2,z+h/2) if axis else ((a+b)/2,y0,z+h/2);dims=(.22,b-a,h) if axis else (b-a,.22,h);box(name+str(i),loc,dims,wall)

def product(folder,index,loc,rot=0,key='product'):
 scope=json.loads((SRC/folder/'review_scope.json').read_text());entry=scope['assets'][index];studio=SRC/folder/'review_studio.blend'
 with bpy.data.libraries.load(str(studio),link=False) as (a,b):b.objects=entry['objects']
 obs=[o for o in b.objects if o]
 for o in obs:bpy.context.scene.collection.objects.link(o)
 bpy.context.view_layer.update() # mandatory evaluated parent pose before capture
 for o in obs:M=o.matrix_world.copy();o.parent=None;o.matrix_world=M
 bpy.context.view_layer.update();ps=[o.matrix_world@v.co for o in obs if o.type=='MESH' for v in o.data.vertices];lo=Vector([min(p[k] for p in ps) for k in range(3)]);hi=Vector([max(p[k] for p in ps) for k in range(3)]);dims=hi-lo
 declared=entry.get('extents_m',entry.get('original_world_extents_m',entry.get('native_extent_m')))
 if declared:assert max(abs(x-y) for x,y in zip(dims,declared))<.001,(folder,dims,declared)
 origin=Vector(((lo.x+hi.x)/2,(lo.y+hi.y)/2,lo.z));M=Matrix.Translation(Vector(loc))@Matrix.Rotation(rot,4,'Z')@Matrix.Translation(-origin)
 for o in obs:o.matrix_world=M@o.matrix_world;o.name=key+'_'+o.name;o['native_product_id']=entry['id'];o['unit_scale_preserved']=True
 rows.append({'key':key,'source':str(studio),'asset_id':entry['id'],'source_dimensions_xyz_m':list(dims),'placed_center_floor_m':loc,'rotation_z':rot,'scale_change':False,'polygons':sum(len(o.data.polygons) for o in obs if o.type=='MESH')});return obs

try:
 state(phase='architecture_authoring')
 if duplex:bpy.ops.wm.read_factory_settings(use_empty=True)
 else:
  shell=B/'scene.blend';assert shell.exists(),'Native penthouse shell must complete first';bpy.ops.wm.open_mainfile(filepath=str(shell))
 rows=[];wall=mat('Warm lime plaster',(.63,.59,.52),.73);stone=mat('Ivory honed limestone',(.48,.44,.37),.36,stone=True);dark=mat('Blackened bronze frames',(.035,.032,.026),.3,.75);glass=mat('Physical 12mm clear glazing IOR1.5',(.95,.97,.98),glass=True);wood=mat('Oiled walnut construction',(.16,.077,.033),.4);metal=mat('Satin brass fixings',(.38,.25,.10),.24,.8)
 if duplex:
  # Ground plate; upper ring is four distinct structural slabs, leaving actual void.
  box('L0_structural_floor',(8,7,-.13),(16,14,.26),stone)
  for name,loc,dims in [('west',(2.5,7,3.29),(5,14,.22)),('east',(13.5,7,3.29),(5,14,.22)),('south',(8,1.5,3.29),(6,3,.22)),('north',(8,12.5,3.29),(6,3,.22))]:box('L1_'+name+'_structural_slab',loc,dims,stone)
  walls('north_back',0,14,16,14,h=6.6)
  walls('west_outer',0,0,0,14,h=6.6)
  walls('L0_study_north',0,3,5,3,doors=3.6);walls('L0_study_east',5,0,5,3,doors=1.5);walls('L0_wc_west',13,0,13,3,doors=1.4);walls('L0_wc_north',13,3,16,3)
  walls('L0_utility',0,11,5,11,doors=3.7)
  for name,a in [('bed3',(0,5,5,5,3.4,3.2,3.6)),('bath',(0,8,5,8,3.4,3.2,3.6)),('dress',(0,11,5,11,3.4,3.2,3.6)),('bed2',(11,5,16,5,3.4,3.2,12.3)),('master',(11,7,16,7,3.4,3.2,12.3))]:walls('L1_'+name,*a[:4],z=a[4],h=a[5],doors=a[6])
  # Straight stair:20 risers 170mm,19 treads300mm. Concrete treads supported by two real stringers.
  for i in range(20):box(f'Stair_tread_{i:02}',(10.3,4.9+i*.3,(i+1)*.17-.055),(1.25,.30,.11),stone,.01)
  for x in [9.82,10.78]:beam('Inclined_steel_stair_stringer',(x,4.75,-.07),(x,10.8,3.28),.13,dark)
  # Upper landing connects to ring north, not floating above the void.
  box('Stair_top_landing',(10.3,11.35,3.29),(1.4,1.1,.22),stone)
  for x in [9.65,10.95]:
   for i in range(0,20,4):beam('Stair_guard_post',(x,4.9+i*.3,(i+1)*.17),(x,4.9+i*.3,(i+1)*.17+1),.035,dark)
   beam('Climbable_stair_hand_rail',(x,4.9,1.17),(x,10.6,4.4),.045,metal)
  # Guard panels include 12mm glass and brackets, clear openings only at actual stair landing.
  for name,loc,dims in [('west',(5.03,7,3.95),(.012,8,1.1)),('south',(8,3.03,3.95),(6,.012,1.1)),('north',(7.25,10.97,3.95),(4.5,.012,1.1))]:
   box('Upper_void_guard_'+name,loc,dims,glass,.003)
   for t in [-.4,.4]:
    p=list(loc);axis=1 if dims[1]>dims[0] else 0;p[axis]+=dims[axis]*t;p[2]=3.46;box('Glass_guard_steel_shoe',p,(.07,.08,.12),dark,.003)
  dims=(16,14);height=6.6
 else:dims=(23,14);height=3.2
 W,H=dims
 # South panorama glazing; penthouse adds north terrace glazing; full height duplex windows split at structural level.
 for side,y in [('south',0),('north',H)] if not duplex else [('south',0)]:
  for i in range(math.ceil(W/2)):
   x0=i*2;x1=min(W,(i+1)*2)
   box(side+'_physical_glass_'+str(i),((x0+x1)/2,y,height/2),(x1-x0-.06,.012,height-.08),glass,.002)
   box(side+'_mullion_'+str(i),(x0,y,height/2),(.055,.08,height),dark,.004)
  for z in [0,height]:box(side+'_continuous_header', (W/2,y,z),(W,.09,.07),dark,.005)
 box('South_terrace_structural_plate',(W/2,-1.45,-.14),(W,2.9,.28),stone)
 for i in range(math.ceil(W/2)):
  x=i*2+1;box('Terrace_glass_guard_'+str(i),(x,-2.85,.58),(1.94,.012,1.1),glass,.002);box('Terrace_post_'+str(i),(x-.97,-2.85,.58),(.035,.035,1.16),dark,.004)
 # First context furniture: actual native-source product assemblies, all rigid native size.
 state(phase='appending_native_high_detail_products')
 if duplex:
  product('real_living_right_sofa_candidate',0,(7.7,6.2,0),math.pi/2,'L0_living_sofa');product('real_table_candidates',0,(7.5,4.9,0),key='L0_living_coffee')
  product('real_living_right_sofa_candidate',0,(12.7,1.4,0),0,'entry_lounge_sofa')
  beds=[(13.6,10.4,3.4),(13.5,2.6,3.4),(2.6,2.6,3.4)];baths=[(14.8,1.2,0),(1.5,6.5,3.4),(5.9,12.4,3.4)]
  treepos=[(8,10,0),(6,10,0),(14,-1.4,0),(1,-1.4,0)]
 else:
  product('real_living_right_sofa_candidate',0,(9,11,0),math.pi/2,'living_sectional');product('real_table_candidates',0,(7.5,10.8,0),key='living_coffee');product('real_living_right_sofa_candidate',0,(10.2,2.7,0),math.pi/2,'family_sofa')
  beds=[(3.0,2.5,0),(14.6,1.6,0),(20.5,1.6,0)];baths=[(7.1,1.5,0),(14.5,4.5,0),(18.5,4.5,0),(21.6,4.5,0)];treepos=[(6,13,0),(11,13,0),(18,13,0),(2,-1.4,0),(21,-1.4,0)]
 for i,p in enumerate(beds):product('real_bed_candidates',i%3,p,0,f'bedroom_{i+1}_actual_bed')
 for i,p in enumerate(baths):product('sanitary106_complete_products',1,p,0,f'bathroom_{i}_adult_toilet');product('sanitary106_complete_products',0,(p[0]+1,p[1],p[2]),0,f'bathroom_{i}_pedestal_basin')
 for i,p in enumerate(treepos):product('real_indoor_tree_candidates',0,p,0,f'native_olive_tree_{i}')
 # True dining table from curated original native product studio.
 contract=json.loads((REF/'commercial_office_floor_02/real_table_candidates/warm_elsa_contract.json').read_text());
 with bpy.data.libraries.load(contract['candidate'],link=False) as (a,b):b.objects=contract['objects']
 table=b.objects[0];bpy.context.scene.collection.objects.link(table);bpy.context.view_layer.update();ps=[table.matrix_world@v.co for v in table.data.vertices];lo=Vector([min(p[k] for p in ps) for k in range(3)]);hi=Vector([max(p[k] for p in ps) for k in range(3)]);dc=(13.7,7.2,0) if duplex else (14,10.8,0);table.matrix_world=Matrix.Translation(Vector(dc)-Vector(((lo.x+hi.x)/2,(lo.y+hi.y)/2,lo.z)))@table.matrix_world;table.name='Actual_native_dining_table';rows.append({'key':'dining_table','source':contract['candidate'],'dimensions_xyz_m':list(hi-lo),'scale_change':False})
 for i,(dx,dy,rot) in enumerate([(-.7,-1.2,0),(.7,-1.2,0),(-.7,1.2,math.pi),(.7,1.2,math.pi)]):product('living108_armchair_products',0,(dc[0]+dx,dc[1]+dy,0),rot,'dining_native_chair_'+str(i))
 for i,p in enumerate([(3,-1.5,0),(4.4,-1.5,0)]):product('living108_armchair_products',0,p,0,'terrace_chair_'+str(i))
 product('real_table_candidates',1,(3.7,-1.5,0),key='terrace_side_table')
 # City construction is consistent for all floors/cameras; individual facade floors/windows have depth.
 random.seed(seed)
 city=mat('Distant_city_concrete',(.22,.27,.32),.7);win=mat('City_low_e_glass',(.16,.23,.29),.23,.3)
 for i in range(28):
  x=-30+i*3.6;y=-22-random.random()*22;w=random.uniform(2,4);h=random.uniform(5,28);box('City_building_'+str(i),(x,y,-25+h/2),(w,random.uniform(2,4),h),city,.04)
  for z in range(-22,int(-25+h),2):box('City_facade_band',(x,y+2.1,z),(w+.02,.025,.9),win,.003)
 # Physical ceiling slabs are hidden only in overview. Double-height void keeps6.6m.
 box(scene+'.ceiling',(W/2,H/2,height+.12),(W,H,.24),wall)
 world=bpy.data.worlds.new('Clear_city_daylight');world.use_nodes=True;world.node_tree.nodes['Background'].inputs['Color'].default_value=(.63,.75,.9,1);world.node_tree.nodes['Background'].inputs['Strength'].default_value=.35;bpy.context.scene.world=world
 sun=bpy.data.lights.new('Sun_late_afternoon','SUN');sun.energy=2.2;sun.angle=.12;o=bpy.data.objects.new(sun.name,sun);bpy.context.scene.collection.objects.link(o);o.rotation_euler=(.5,-.5,-.6)
 for i,(x,y,z) in enumerate([(W/2,2,height-.25),(W/2,H-2,height-.25),(2,7,3)]):
  l=bpy.data.lights.new('Integrated_ceiling_soft_'+str(i),'AREA');l.energy=650;l.shape='DISK';l.size=5;o=bpy.data.objects.new(l.name,l);bpy.context.scene.collection.objects.link(o);o.location=(x,y,z)
 bpy.context.view_layer.update();bpy.ops.wm.save_as_mainfile(filepath=str(out))
 views=[{'name':'overview','overview':True,'location':(W*.8,-H*.8,25),'target':(W/2,H/2,2 if duplex else 0),'ortho_scale':W*1.65,'render_width':800},{'name':'living_context','location':(6,2,1.65) if duplex else (6.2,8.7,1.65),'target':(11,9,2.2) if duplex else (12,13,1.5),'hfov':75,'render_width':800}]
 (D/'views_r001.json').write_text(json.dumps(views,indent=2));(D/'native_products_r001.json').write_text(json.dumps({'products':rows,'scale_policy':'Rigid translation/rotation only; evaluated original source dimensions preserved in all3axes','geometry_acceptance':False,'visual_acceptance':False},indent=2));state(phase='saved_render_pending',candidate=str(out),product_count=len(rows),exit_code=0,finished_unix=time.time())
except BaseException as e:state(phase='failed',error=repr(e),traceback=traceback.format_exc(),exit_code=1);raise
