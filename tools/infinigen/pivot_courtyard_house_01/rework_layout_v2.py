"""Authorized courtyard-facing kitchen/living layout stage. Not a final candidate."""
import bpy,math,json,sys
from pathlib import Path
from mathutils import Matrix,Vector
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT/'tools/infinigen'))
from room_planner import proc_assets as pa
pa.SURFACE_DETAIL=False
B=ROOT/'data/venue_refs/floor_plans_v3/pivot_courtyard_house_01';F=ROOT/'out/infinigen_v2/kr_pivotHouse_48712501/full'
def flat(n,c,r=.6):
 m=bpy.data.materials.new(n);m.use_nodes=True;p=m.node_tree.nodes['Principled BSDF'];p.inputs['Base Color'].default_value=(*c,1);p.inputs['Roughness'].default_value=r;return m
oak=pa._flat('layout_v2_oak',(.39,.27,.16),.55,wood=True);wall=bpy.data.materials['ir_late_wall_flat'];stone=bpy.data.materials['pivot_r14_limestone'];dark=flat('layout_v2_dark_frame',(.018,.024,.026),.3);glass=flat('layout_v2_glazing',(.97,.99,1),.055);p=glass.node_tree.nodes['Principled BSDF'];p.inputs['Transmission Weight'].default_value=1;p.inputs['IOR'].default_value=1.45
binmat=flat('layout_v2_storage_bin',(.08,.11,.13));steel=flat('layout_v2_steel',(.26,.28,.29),.35)
def box(c,s):return ('box',c,s,(0,0,0))
def create(n,groups,room):
 o=pa._prims('PivotLayoutV2_'+n,groups);o['ir_room']=room;o['ir_layout_stage']='courtyard_v2';return o
def cut(o,center,size):
 bpy.ops.mesh.primitive_cube_add(size=1,location=center);c=bpy.context.object;c.dimensions=size;bpy.ops.object.transform_apply(location=False,rotation=False,scale=True)
 mod=o.modifiers.new('authorized_glazed_opening','BOOLEAN');mod.operation='DIFFERENCE';mod.solver='EXACT';mod.object=c
 bpy.context.view_layer.objects.active=o;bpy.ops.object.modifier_apply(modifier=mod.name);bpy.data.objects.remove(c,do_unlink=True)
# Preserve old kitchen architectural cell as a family dining connection.
for o in list(bpy.data.objects):
 if o.name=='kitchen_0/0' or o.name.startswith('kitchen_0/0.'):
  o.name=o.name.replace('kitchen_0/0','dining-room_0/1',1)
# Clone existing garage architecture for kitchen, move original garage to annex.
translation=Vector((10,5,0));oldgarage=[o for o in list(bpy.data.objects) if o.name=='garage_0/0' or o.name.startswith('garage_0/0.')]
for o in oldgarage:
 clone=o.copy();clone.data=o.data.copy();clone.name=o.name.replace('garage_0/0','kitchen_0/0',1)
 for coll in o.users_collection:coll.objects.link(clone)
 clone['ir_layout_stage']='courtyard_kitchen_v2';o.location+=translation
# Move garage furnishing; remove placeholder rack for replacement residential storage.
for o in list(bpy.data.objects):
 if o.get('ir_room')=='garage_0/0' and o.parent is None:
  if 'StorageRackFactory' in o.name:
   for child in list(o.children_recursive):bpy.data.objects.remove(child,do_unlink=True)
   bpy.data.objects.remove(o,do_unlink=True)
  else:o.location+=translation
# Rotate former 3.6m kitchen run onto east wall; its front now faces west/courtyard.
transform=Matrix.Translation(Vector((21.48,6.45,0)))@Matrix.Rotation(math.pi/2,4,'Z')@Matrix.Translation(Vector((-13.650542,9.533542,0)))
for o in list(bpy.data.objects):
 if o.get('ir_room')=='kitchen_0/0' and o.parent is None and not o.name.startswith('kitchen_0/0'):
  o.matrix_world=transform@o.matrix_world
# Move original garage pendant to new garage, add kitchen soft ceiling area.
lamp=bpy.data.objects.get('PointLampFactory(added).spawn_asset(11)')
if lamp:lamp.location+=translation
ld=bpy.data.lights.new('courtyard_kitchen_softlight','AREA');ld.energy=180;ld.shape='DISK';ld.size=2.4;lo=bpy.data.objects.new(ld.name,ld);bpy.context.scene.collection.objects.link(lo);lo.location=(19,6.5,2.60)
# Replace the east garage door opening with a real plaster wall in new kitchen.
create('kitchen_east_infill',[(wall,[box((21.93,6.5,1.4),(.15,5,2.8))])],'kitchen_0/0')
# Actual full-height opening through both interior and exterior wall meshes.
for suffix in ['.wall','.exterior']:
 o=bpy.data.objects['kitchen_0/0'+suffix];cut(o,(16.57,6.5,1.36),(.65,4.45,2.45))
# Glazing is thin closed physical glass, separated by slender dark mullions.
parts=[box((16.55,y,1.36),(.065,.045,2.45)) for y in [4.275,5.3875,6.5,7.6125,8.725]]
parts +=[box((16.55,6.5,z),(.065,4.50,.045)) for z in [.155,2.565]]
create('courtyard_kitchen_frames',[(dark,parts)],'kitchen_0/0')
create('courtyard_kitchen_glass',[(glass,[box((16.55,(a+b)/2,1.36),(.012,b-a-.045,2.365)) for a,b in zip([4.275,5.3875,6.5,7.6125],[5.3875,6.5,7.6125,8.725])])],'kitchen_0/0')
# Island kept 1m+ from glass and east run; pantry doorway at x17 remains free.
create('kitchen_island',[(oak,[box((19,6.5,.57),(1.05,2.05,.84))]),(stone,[box((19,6.5,1.015),(1.15,2.15,.05))])],'kitchen_0/0')
# Far living facade: keep pre-existing connecting door at x16.7..17.6 intact.
for suffix in ['.wall','.exterior']:
 o=bpy.data.objects.get('living-room_0/2'+suffix)
 if o:cut(o,(14.85,3.94,1.36),(3.25,.65,2.45))
create('courtyard_living_frames',[(dark,[box((x,3.95,1.36),(.045,.065,2.45)) for x in [13.225,14.3083,15.3917,16.475]]+[box((14.85,3.95,z),(3.295,.065,.045)) for z in [.155,2.565]])],'living-room_0/2')
create('courtyard_living_glass',[(glass,[box(((a+b)/2,3.95,1.36),(b-a-.045,.012,2.365)) for a,b in zip([13.225,14.3083,15.3917],[14.3083,15.3917,16.475])])],'living-room_0/2')
# Moved garage shared-door gaps now face exterior: close them with solid walls.
create('garage_closed_old_connections',[(wall,[box((29.25,y,1.4),(5.5,.16,2.8)) for y in [9.06,13.94]])],'garage_0/0')
# Residential oak shelf wall with usable bins, tool cases and hanging hose.
parts=[]
for z in [.30,.85,1.40,1.95,2.35]:parts.append(box((27.05,11.5,z),(.60,3.6,.045)))
for y in [9.70,11.5,13.30]:parts.append(box((27.05,y,1.325),(.60,.045,2.095)))
create('garage_residential_shelves',[(oak,parts)],'garage_0/0')
for j,z in enumerate([.3225,.8725,1.4225]):
 for i,y in enumerate([10.14,10.93,12.04,12.83]):
  create('garage_bin_%d_%d'%(j,i),[(binmat,[box((27.06,y,z+.17),(.42,.60,.34)),box((27.06,y,z+.355),(.45,.63,.03))]),(steel,[box((27.285,y,z+.20),(.012,.18,.035))])],'garage_0/0')
# Semantic camera locations follow relocated room; retain original as baseline evidence.
views=json.loads((F/'review_views_r21.json').read_text())
for v in views:
 n=v['name']
 if n.startswith('garage'):
  v['baseline_location']=v['location'];v['baseline_target']=v['target'];v['location']=[a+b for a,b in zip(v['location'],translation)];v['target']=[a+b for a,b in zip(v['target'],translation)];v['layout_change']='garage relocated to external annex'
 if n.startswith('kitchen'):
  v['baseline_location']=v['location'];v['baseline_target']=v['target'];v['location']=[17.3,8.0,1.65];v['target']=[20.4,6.4,1.2];v['layout_change']='kitchen moved to courtyard facade'
(F/'review_views_layout_v2.json').write_text(json.dumps(views,indent=2)+'\n')
bpy.context.view_layer.update();floors=[o.name for o in bpy.data.objects if o.name.endswith('.floor')];assert len(floors)==29,(len(floors),floors)
assert len([n for n in floors if n.startswith('bedroom_')])==5
bpy.context.scene['pivot_revision']='layout_v2_work_in_progress';bpy.ops.wm.save_as_mainfile(filepath=str(F/'scene_rework_layout_v2.blend'))
(B/'layout_stage_v2.json').write_text(json.dumps({'status':'geometry_saved_visual_validation_pending','floor_count':len(floors),'bedroom_count':5,'scene':str(F/'scene_rework_layout_v2.blend'),'views':str(F/'review_views_layout_v2.json'),'required_remaining':['Facade ray and visual inspection','Garage access and connection review','Former kitchen re-furnishing','Rich courtyard landscaping','Entry deck full rework','Reference and navigation plan update','All affected room regression inspection'],'not_final':True},indent=2)+'\n');print('PIVOT_LAYOUT_V2_SAVED',flush=True)
