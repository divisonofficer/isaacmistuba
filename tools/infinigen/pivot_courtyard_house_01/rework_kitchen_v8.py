"""Orient the kitchen work run toward the courtyard camera, preserving clear aisles."""
import bpy,json,math,sys
from pathlib import Path
from mathutils import Matrix,Vector
R=Path(__file__).resolve().parents[3];sys.path.insert(0,str(R/'tools/infinigen'))
from room_planner import proc_assets as pa
B=R/'data/venue_refs/floor_plans_v3/pivot_courtyard_house_01';F=R/'out/infinigen_v2/kr_pivotHouse_48712501/full'
old=Matrix.Translation(Vector((21.48,6.45,0)))@Matrix.Rotation(math.pi/2,4,'Z')@Matrix.Translation(Vector((-13.650542,9.533542,0)))
new=Matrix.Translation(Vector((6,-4.983542,0)))
for o in bpy.data.objects:
 if o.parent is None and o.get('ir_room')=='kitchen_0/0' and o.name.startswith(('HomeKitchenRunFactory','PivotFridgeFrontDetailFactory')):o.matrix_world=new@old.inverted()@o.matrix_world
island=bpy.data.objects['PivotLayoutV2_kitchen_island'];island.matrix_world=Matrix.Translation(Vector((19.65,6.40,0)))@Matrix.Rotation(math.pi/2,4,'Z')@Matrix.Translation(Vector((-19,-6.5,0)))@island.matrix_world
pa.STYLE['chair_style']='light_wood'
for i,x in enumerate([19.1,20.15]):
 o=pa.CounterStoolFactory(48712880+i).spawn_asset(2880+i);o.location=(x,7.32,.14754);o.rotation_euler.z=-math.pi/2;o['ir_room']='kitchen_0/0'
# Keep oak kitchen fronts consistent with the reference; genuine appliance materials retained.
run=next(o for o in bpy.data.objects if o.name.startswith('HomeKitchenRunFactory') and o.get('ir_room')=='kitchen_0/0')
for slot in run.material_slots:
 if slot.material and slot.material.name.startswith('ir_kit_front_'):slot.material=bpy.data.materials['layout_v2_oak']
bpy.context.view_layer.update();rows=[]
for o in [run,island]:
 pts=[o.matrix_world@Vector(v) for v in o.bound_box];rows.append({'object':o.name,'bounds':[[min(v[k] for v in pts),max(v[k] for v in pts)] for k in range(3)]})
# This measured aisle is a geometric constraint, not a visual pass.
assert rows[1]['bounds'][1][0]-rows[0]['bounds'][1][1]>.85,rows
bpy.ops.wm.save_as_mainfile(filepath=str(F/'scene_rework_kitchen_v8.blend'))
(B/'kitchen_stage_v8.json').write_text(json.dumps({'status':'geometry_saved_visual_review_pending','bounds':rows,'changes':['Kitchen run moved to south wall facing courtyard rather than hidden at oblique east wall','Island rotated and positioned with >0.85m working aisle','Two light-oak counter stools','Oak fronts with appliance materials preserved'],'remaining':['Original courtyard and kitchen render review','Guest connection and pantry doorway clearances','Add missing domestic details based on visual comparison']},indent=2)+'\n');print('PIVOT_KITCHEN_V8_SAVED',flush=True)
