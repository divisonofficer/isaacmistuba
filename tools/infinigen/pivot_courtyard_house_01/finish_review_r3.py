"""Close threshold gaps and align finishes after direct interior review."""
import argparse,json,sys
from pathlib import Path
import bpy,shapely
from mathutils import Vector

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'tools/infinigen'))
from room_planner import proc_assets as pa
from room_planner.proc_home import FicusPlantFactory

p=argparse.ArgumentParser();p.add_argument('blend');p.add_argument('--out',required=True);a=p.parse_args()
bpy.ops.wm.open_mainfile(filepath=a.blend)
floor=bpy.data.objects['living-room_0/1.floor'];fz=max((floor.matrix_world@Vector(c)).z for c in floor.bound_box)
doc=json.loads((ROOT/'data/venue_refs/floor_plans_v3/pivot_courtyard_house_01/floor_plan.json').read_text())
poly=shapely.union_all([eval(v['shape']) for v in doc['rooms'].values()])
pts=list(poly.exterior.coords)[:-1]
if sum(x*y1-x1*y for (x,y),(x1,y1) in zip(pts,pts[1:]+pts[:1]))<0:pts.reverse()
me=bpy.data.meshes.new('pivot_continuous_subfloor');me.from_pydata([(x,y,fz-.003) for x,y in pts],[],[list(range(len(pts)))]);me.update()
o=bpy.data.objects.new('PivotContinuousFloorFactory(703).spawn_asset(703)',me);bpy.context.scene.collection.objects.link(o)
stone=pa._flat('pivot_threshold_stone',(.43,.41,.38),.65);o.data.materials.append(stone)
solid=o.modifiers.new('structural slab','SOLIDIFY');solid.thickness=.12;solid.offset=-1
oak=pa._flat('pivot_ref_oak',(.52,.37,.22),.55,wood=True)
linen=pa._flat('pivot_ref_seat',(.59,.55,.48),.85)
changed=0
for o in bpy.data.objects:
 if o.type!='MESH':continue
 if 'TableDiningFactory' in o.name or ('ChairFactory' in o.name and not any(x in o.name for x in ('OfficeChair','BalconyChair'))):
  o.data=o.data.copy()
  for sl in o.material_slots:
   if sl.material:sl.material=linen if any(x in sl.material.name.lower() for x in ('fabric','cloth','leather')) else oak
  changed+=1
 if 'HomeKitchenRunFactory' in o.name:
  o.data=o.data.copy()
  for sl in o.material_slots:
   if sl.material and sl.material.name.startswith('ir_kit_front_'):sl.material=oak
 if 'WindowFactory' in o.name:
  for sl in o.material_slots:
   m=sl.material
   if m and m.use_nodes and any(k in m.name.lower() for k in ('glass','frost')):
    for n in m.node_tree.nodes:
     if n.type=='BSDF_PRINCIPLED':
      n.inputs['Transmission Weight'].default_value=1;n.inputs['Roughness'].default_value=.035
      n.inputs['Base Color'].default_value=(.94,.97,1,1)
if bpy.context.scene.world:
 for n in bpy.context.scene.world.node_tree.nodes:
  if n.type=='BACKGROUND':n.inputs['Color'].default_value=(.65,.75,.9,1);n.inputs['Strength'].default_value=.35
tree=FicusPlantFactory(48712501).spawn_asset(703);tree.location=(11.5,6.2,fz);tree.scale=(2.2,2.2,2.2)
bpy.context.view_layer.update()
bpy.context.scene['pivot_revision']='r3_direct_review'
bpy.ops.wm.save_as_mainfile(filepath=a.out)
Path(a.out).with_suffix('.review.json').write_text(json.dumps({'continuous_floor_area_m2':poly.area,
 'threshold_top_below_room_floor_m':.003,'dining_meshes_restyled':changed,
 'changes':['continuous foundation closes black opening gaps','light oak dining and kitchen fronts','clear window glass and daylight','courtyard ficus'],
 'limitations':['absolute dimensions estimated','courtyard tree is procedural ficus rather than surveyed landscape']},indent=2))
print('PIVOT_R3_COMPLETE',flush=True)
