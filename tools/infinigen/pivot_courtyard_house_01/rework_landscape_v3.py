"""Layered courtyard borders using eight cached Infinigen plant geometries."""
import bpy,json,random,math,sys
from pathlib import Path
from mathutils import Vector
R=Path(__file__).resolve().parents[3];sys.path.insert(0,str(R/'tools/infinigen'))
from room_planner import proc_assets as pa
B=R/'data/venue_refs/floor_plans_v3/pivot_courtyard_house_01';F=R/'out/infinigen_v2/kr_pivotHouse_48712501/full';rng=random.Random(48712533)
soil=pa._flat('courtyard_v3_soil',(.095,.065,.035),.95)
# Grounded planting beds preserve east/north circulation and clear glazing.
beds=[('box',(8.58,6.12,.13),(.95,3.85,.08),(0,0,0)),('box',(12.12,4.52,.13),(6.1,.64,.08),(0,0,0))]
o=pa._prims('PivotCourtyardV3_PlantingBeds',[(soil,beds)]);o['ir_room']='courtyard'
files=sorted((R/'data/plant_library').glob('plant_*.blend'));assert len(files)>=8
sources=[]
for path in files:
 with bpy.data.libraries.load(str(path),link=False) as (src,dst):dst.objects=[n for n in src.objects if n=='ir_plant']
 source=next(o for o in dst.objects if o);sources.append(source)
placements=[]
# West: richer taller shrubs to rear, low layer towards open lawn.
for i in range(8):placements.append((8.43+rng.uniform(-.08,.08),4.52+i*.43,rng.uniform(.55,.95),'mid'))
for i in range(11):placements.append((8.85+rng.uniform(-.07,.04),4.43+i*.32,rng.uniform(.22,.40),'low'))
# Far border layered below living windows. Keep kitchen/living door clear at x16.7.
for i in range(12):placements.append((9.37+i*.49,4.38+rng.uniform(-.04,.03),rng.uniform(.42,.74),'mid'))
for i in range(16):placements.append((9.26+i*.37,4.72+rng.uniform(-.05,.04),rng.uniform(.20,.36),'low'))
rows=[]
for i,(x,y,h,layer) in enumerate(placements):
 src=sources[(i*3+i//8)%len(sources)];o=src.copy();o.data=src.data;bpy.context.scene.collection.objects.link(o);o.name='PivotCourtyardV3_Plant_%02d'%i;o.parent=None;o.location=(0,0,0);o.rotation_euler=(0,0,rng.uniform(0,math.tau));o.scale=(1,1,1);bpy.context.view_layer.update()
 pts=[o.matrix_world@Vector(v) for v in o.bound_box];height=max(p.z for p in pts)-min(p.z for p in pts);factor=h/max(height,.01);o.scale*=factor;o.location.x=x;o.location.y=y;bpy.context.view_layer.update();pts=[o.matrix_world@Vector(v) for v in o.bound_box];o.location.z=.17-min(p.z for p in pts)
 o['ir_room']='courtyard';o['ir_role']='border_'+layer;o['ir_native_source']=files[sources.index(src)].name
 rows.append({'name':o.name,'source':o['ir_native_source'],'height_m':h,'layer':layer,'location':list(o.location)})
# Unlinked library source objects need no scene membership; remove unused IDs only.
for o in sources:
 if not o.users_collection:bpy.data.objects.remove(o,do_unlink=True)
bpy.context.view_layer.update();bpy.context.scene['pivot_revision']='landscape_v3_work_in_progress';bpy.ops.wm.save_as_mainfile(filepath=str(F/'scene_rework_landscape_v3.blend'))
(B/'landscape_stage_v3.json').write_text(json.dumps({'status':'geometry_saved_visual_review_pending','plant_count':len(rows),'source_variant_count':len(files),'plants':rows,'limitations':['Ground contact uses actual transformed mesh bounds','No visual acceptance before same-camera render','Flowering and foliage character still require comparison to reference']},indent=2)+'\n');print('PIVOT_LANDSCAPE_V3_SAVED',len(rows),flush=True)
