"""Move the original island/seating/pendant into the relocated kitchen; remove temporary duplicate."""
import bpy,json
from pathlib import Path
from mathutils import Vector
R=Path(__file__).resolve().parents[3];B=R/'data/venue_refs/floor_plans_v3/pivot_courtyard_house_01';F=R/'out/infinigen_v2/kr_pivotHouse_48712501/full'
island=next(o for o in bpy.data.objects if 'KitchenIslandFactory' in o.name);pts=[island.matrix_world@Vector(v) for v in island.bound_box];cx=(min(v.x for v in pts)+max(v.x for v in pts))/2;cy=(min(v.y for v in pts)+max(v.y for v in pts))/2;delta=Vector((19.65-cx,6.4-cy,0));moved=[]
for o in list(bpy.data.objects):
 if o.name=='PivotLayoutV2_kitchen_island' or o.name.startswith(('CounterStoolFactory(2880)','CounterStoolFactory(2881)')):
  for child in list(o.children_recursive):bpy.data.objects.remove(child,do_unlink=True)
  bpy.data.objects.remove(o,do_unlink=True)
for o in list(bpy.data.objects):
 if o is island or o.name.startswith(('CounterStoolFactory(1410)','CounterStoolFactory(1411)','CounterStoolFactory(1412)')):
  o.location+=delta;o['ir_room']='kitchen_0/0';moved.append(o.name)
pendants=[o for o in bpy.data.objects if o.parent is None and 'LinearPendantFactory' in o.name]
for o in pendants:
 # Only original island pendant lies at the known old island center.
 if abs(o.location.x-cx)<.2 and abs(o.location.y-cy)<.2:
  o.location+=delta;o.location.z=2.64;o.scale.z*=.75;o['ir_room']='kitchen_0/0';moved.append(o.name)
# Native-leaf upright growth complements the trailing vines instead of a flat strip.
import math,random
rng=random.Random(48712020)
for i,(x,y) in enumerate([(19.85,9.30),(17.15,11.15)]):
 root=bpy.data.objects['PivotPantryV19_vine_'+str(i)];z=2.27704;leaves=[o for o in root.children if 'native_leaf' in o.name]
 for j in range(16):
  a=j*math.tau/16;rad=rng.uniform(.035,.11);end=Vector((x+rad*math.cos(a),y+rad*math.sin(a),z+rng.uniform(.04,.105)))
  curve=bpy.data.curves.new('pantry_v20_upright_stem','CURVE');curve.dimensions='3D';curve.bevel_depth=.0015;curve.bevel_resolution=2;sp=curve.splines.new('POLY');sp.points.add(1);sp.points[0].co=(x,y,z,1);sp.points[1].co=(*end,1)
  o=bpy.data.objects.new('PivotPantryV20_upright_stem_%d_%d'%(i,j),curve);bpy.context.scene.collection.objects.link(o);curve.materials.append(bpy.data.materials['pantry_v19_native_leaf_0']);o.parent=root
  src=leaves[j%len(leaves)];o=src.copy();bpy.context.scene.collection.objects.link(o);o.name='PivotPantryV20_top_leaf_%d_%d'%(i,j);o.parent=root;o.location=end;o.rotation_euler=(rng.uniform(-.5,.5),rng.uniform(-.5,.5),a);o.scale*=1.12
bpy.context.view_layer.update();pts=[island.matrix_world@Vector(v) for v in island.bound_box];run=next(o for o in bpy.data.objects if o.name.startswith('HomeKitchenRunFactory'));rp=[run.matrix_world@Vector(v) for v in run.bound_box];aisle=min(p.y for p in pts)-max(p.y for p in rp);assert aisle>.90,aisle
bpy.context.scene['pivot_revision']='quality_rework_v20';bpy.ops.wm.save_as_mainfile(filepath=str(F/'scene_rework_integrated_v20.blend'));(B/'kitchen_reconciliation_v20.json').write_text(json.dumps({'status':'geometry_saved_full_regression_pending','moved_original_assets':moved,'removed':'Temporary box island and two temporary stools; original island with three stools retained instead','kitchen_working_aisle_m':aisle,'reason':'Avoid two redundant parallel counters behind the new family breakfast bar after relocating the original kitchen','remaining':['Kitchen/family/dining visual regressions','Full 37-camera review','All four required visual gates and final packing/registration']},indent=2)+'\n');print('PIVOT_INTEGRATED_V20_SAVED',moved,flush=True)
