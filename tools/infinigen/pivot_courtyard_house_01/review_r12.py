"""Remaining layout/illumination defects and modest residential dressing."""
import bpy,json,sys,math
from pathlib import Path
from mathutils import Vector
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT/'tools/infinigen'))
from room_planner import proc_assets as pa
from room_planner.proc_home import RecessedSpotFactory
pa.SURFACE_DETAIL=False
base=ROOT/'data/venue_refs/floor_plans_v3/pivot_courtyard_house_01';run=ROOT/'out/infinigen_v2/kr_pivotHouse_48712501/full';fixes=[]
def remove(o):
 for q in reversed([o,*o.children_recursive]):bpy.data.objects.remove(q,do_unlink=True)
def bounds(o):
 pts=[o.matrix_world@Vector(v) for v in o.bound_box]
 return [(min(v[i] for v in pts),max(v[i] for v in pts)) for i in range(3)]
# Correct BED02's headboard to the west wall, with a clear route at the foot.
bed=next(o for o in bpy.data.objects if o.get('ir_room')=='bedroom_0/2' and 'SoftBedFactory' in o.name)
bed.location=(.25,13.3,.14754);bed.rotation_euler.z=0;bed.scale=(2.05/2.18,1.6/2.2,1)
removed=[]
for o in list(bpy.data.objects):
 if o.parent is None and o.get('ir_room')=='bedroom_0/2' and any(k in o.name for k in ('Nightstand','SideTable','TableFactory')):removed.append(o.name);remove(o)
oak=pa._flat('pivot_r12_bedside_oak',(.45,.32,.2),.65,wood=True)
for i,y in enumerate((12.2,14.4)):
 o=pa._prims(f'PivotBed02SideFactory({1500+i}).spawn_asset({1500+i})',[(oak,[('box',(.58,y,.14754+.27),(.42,.42,.50),(0,0,0))])]);o['ir_room']='bedroom_0/2'
fixes.append({'issue':'BED02 headboard was freestanding in middle of room','action':'headboard at west wall, bed facing east, paired small nightstands; east door/foot circulation kept clear','old_nightstands_removed':removed})
# Establish the actual ceiling height with rays, not assumed wall-height config.
s=bpy.context.scene;dep=bpy.context.evaluated_depsgraph_get()
hit=s.ray_cast(dep,Vector((5.4,14.75,1.8)),Vector((0,0,1)),distance=3)
assert hit[0], 'WC ceiling ray must hit a surface'
ceiling_z=hit[1].z
assert 2.0<ceiling_z<3.5,(ceiling_z,hit[4].name)
lamp=bpy.data.objects.get('pivot_wc_ceiling');assert lamp;lamp.location.z=ceiling_z-.14;lamp.data.energy=45
spot=bpy.data.objects.get('RecessedSpotFactory(1401).spawn_asset(1401)')
if spot:spot.location.z=ceiling_z-.01
fixes.append({'issue':'WC area light was placed above actual ceiling and remained dark','action':'move light below measured ceiling','ceiling_z_m':ceiling_z,'ceiling_hit':hit[4].name,'light_z_m':lamp.location.z})
# Root geometry extends below each native tree's modelling origin. Use trunk
# mesh vertices rather than all child/proxy bounding boxes to seat external trees.
trees=[]
for rig in [o for o in bpy.data.objects if o.type=='EMPTY' and o.name.startswith('PivotMatureTreeRig')]:
 roots=[o for o in rig.children if o.type=='MESH' and o.get('pivot_native_landscape_tree')]
 if not roots:continue
 root=roots[0];zs=[(root.matrix_world@v.co).z for v in root.data.vertices]
 if not zs:continue
 old=min(zs);rig.location.z+=.06-old;trees.append({'rig':rig.name,'trunk_raw_low_before':old,'rig_z_after':rig.location.z})
fixes.append({'issue':'external trunks still appeared detached from ground','action':'seat each trunk mesh minimum at soil level','trees':trees})
# Refrigerator front detail in the existing factory's local coordinates.
kitchen=next(o for o in bpy.data.objects if 'HomeKitchenRunFactory' in o.name and o.get('ir_room')=='kitchen_0/0')
steel=bpy.data.materials['pivot_r10_clean_metal'];dark=pa._flat('pivot_r12_fridge_seam',(.035,.04,.045),.6)
L=3.6;fy=-L/2+.36
front=pa._prims('PivotFridgeFrontDetailFactory(1510).spawn_asset(1510)',[(dark,[('box',(.704,fy,.70),(.008,.64,.012),(0,0,0))]),(steel,[('box',(.728,fy+.23,1.30),(.035,.022,.54),(0,0,0)),('box',(.728,fy+.23,.49),(.035,.022,.24),(0,0,0))])]);front.matrix_world=kitchen.matrix_world.copy();front['ir_room']='kitchen_0/0'
# A low real flower asset in a ceramic vase, below all eye-level sightlines.
ceramic=pa._flat('pivot_r12_matte_ceramic',(.63,.58,.48),.85)
for i,(x,y,z) in enumerate([(18.12,13.90,.52754),(13.0,14.25,.91)]):
 vase=pa._prims(f'PivotTableVaseFactory({1520+i}).spawn_asset({1520+i})',[(ceramic,[('cyl',(x,y,z+.065),(.055,.045,.13),(0,0,0))])]);vase['pivot_dressing']=True
 with bpy.data.libraries.load(str(ROOT/'data/plant_library/flower_004.blend'),link=False) as (src,dst):
  pick=next((n for n in src.objects if n in ('ir_plant','ir_flower')),None);dst.objects=[pick or src.objects[0]]
 for flower in dst.objects:
  if flower:
   bpy.context.scene.collection.objects.link(flower);bpy.context.view_layer.update();flower.scale*=.28/max(flower.dimensions.z,.01);flower.location=(x,y,z+.10);flower['pivot_dressing']=True
fixes.append({'issue':'reference tables have simple lived-in props; fridge reads as blank box','action':'small native flower assets and ceramic vases; fridge door seam and handles'})
# Camera updates to reveal actual room content.
views=json.loads((run/'review_views_r11.json').read_text())
for v in views:
 if v['name']=='bedroom_0-2_wide1':v.update(location=[3.05,14.9,1.65],target=[1.1,13.3,1.0],hfov=85)
 if v['name']=='utility_0-1_wide0':v.update(location=[20.15,9.55,1.65],target=[18.5,11.0,1.1],hfov=85)
(run/'review_views_r12.json').write_text(json.dumps(views,indent=2))
bpy.context.view_layer.update();invalid=[o.name for o in bpy.data.objects if o.type=='MESH' and any(not math.isfinite(v) or abs(v)>100 for v in o.dimensions)];assert not invalid,invalid
bb=bounds(bed);assert bb[0][0]>.14 and bb[0][1]<2.7 and bb[1][0]>11.65 and bb[1][1]<15.35,bb
s['pivot_revision']='r12_layout_illumination';bpy.ops.wm.save_as_mainfile(filepath=str(run/'scene_review_r12.blend'))
(base/'revision_r12.json').write_text(json.dumps({'fixes':fixes,'invalid_mesh_extents':invalid,'bed02_bounds':bb,'camera_changes':['bedroom_0-2_wide1','utility_0-1_wide0'],'camera_count':len(views)},indent=2));print('PIVOT_R12_COMPLETE',flush=True)
