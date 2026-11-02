"""Replace one sparse office plant with the reviewed native-component assembly trial."""
import bpy,json,hashlib
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree
ROOT=Path(__file__).resolve().parents[3];ref=ROOT/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';base=ROOT/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full'
src=base/'scene_candidate_r57.blend';out=base/'scene_candidate_r58.blend';asset=ref/'assembled_leaf_plant_studio/plant02.blend'
assert not out.exists();review=json.loads((ref/'assembled_leaf_plant_studio/blind_review02.json').read_text());assert review['accepted_for_room_trial']
sha=hashlib.sha256(src.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(src));bpy.context.view_layer.update()
floor=bpy.data.objects['kitchen_0/0.floor'];fz=max((floor.matrix_world@Vector(c)).z for c in floor.bound_box)
removed=[]
for o in list(bpy.data.objects):
 if o.get('program_key') in ['plant_4','pot_4','soil_4']:removed.append(o.name);bpy.data.objects.remove(o,do_unlink=True)
assert len(removed)==3,removed
names=tuple(['Indoor_leaf_'+str(i) for i in range(7)]+['Hollow_planter','Planter_soil'])
with bpy.data.libraries.load(str(asset),link=False) as (a,b):
 assert all(n in a.objects for n in names);b.objects=list(names)
parts=[];delta=Vector((12.9,6.6,fz+.0005))
for i,o in enumerate(b.objects):
 bpy.context.scene.collection.objects.link(o);o.location+=delta;o.name='R58_office_'+names[i];o['reference_scene_owner']='commercial_office_floor_02'
 o['program_key']='plant_4' if i==0 else 'plant_4_component_'+str(i) if i<7 else 'pot_4' if i==7 else 'soil_4';parts.append(o)
visibility={o.name:o.hide_viewport for o in bpy.context.scene.objects if o.type=='MESH' and not o.hide_render}
for name in visibility:bpy.data.objects[name].hide_viewport=False
bpy.context.view_layer.update()
def bounds(o):
 p=[o.matrix_world@Vector(c) for c in o.bound_box];return [[min(q[i] for q in p) for i in range(3)],[max(q[i] for q in p) for i in range(3)]]
part_bounds={o.name:bounds(o) for o in parts};potential=[]
for other in bpy.context.scene.objects:
 if other.type!='MESH' or other in parts or other.hide_render:continue
 bb=bounds(other)
 for name,ab in part_bounds.items():
  if all(ab[0][i]<bb[1][i]-1e-6 and bb[0][i]<ab[1][i]-1e-6 for i in range(3)):potential.append({'part':name,'other':other.name,'other_key':other.get('program_key','')})
def tree(o):
 ev=o.evaluated_get(bpy.context.evaluated_depsgraph_get());m=ev.to_mesh()
 result=BVHTree.FromPolygons([o.matrix_world@v.co for v in m.vertices],[list(f.vertices) for f in m.polygons]);ev.to_mesh_clear();return result
trees={};checked=[]
for pair in potential:
 for name in [pair['part'],pair['other']]:
  if name not in trees:trees[name]=tree(bpy.data.objects[name])
 count=len(trees[pair['part']].overlap(trees[pair['other']]));checked.append({**pair,'triangle_intersections':count})
errors=[q for q in checked if q['triangle_intersections']]
assert not errors,('Exact surface intersections',errors)
for name,value in visibility.items():bpy.data.objects[name].hide_viewport=value
bpy.ops.wm.save_as_mainfile(filepath=str(out));assert hashlib.sha256(src.read_bytes()).hexdigest()==sha
(ref/'realism_refinement_r58.json').write_text(json.dumps({'source':str(src),'source_sha256':sha,'candidate':str(out),'asset':str(asset),'asset_sha256':hashlib.sha256(asset.read_bytes()).hexdigest(),'scope':'One plant/pot/soil replacement only;all other geometry/materials/lights/camera unchanged','removed':removed,'floor_z_m':fz,'planter_floor_gap_m':.0005,'translation_m':list(delta),'part_bounds_m':part_bounds,'visible_scene_mesh_AABB_overlap_candidates':potential,'exact_surface_checks':checked,'collision_scope':'Visible scene external mesh surface intersections after AABB broadphase;not full navigation,containment orroot/soil acceptance','photorealism_accepted':False,'requires':'Saved whole candidate audits andsame wide render;inspect canopy,scale,repetition andmanufacturing/root defects'},indent=2));print('SAVED',out,flush=True)
