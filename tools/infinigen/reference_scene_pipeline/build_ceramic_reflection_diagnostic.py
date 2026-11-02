"""Use a visible body hit and reflection law to position a diagnostic strip light; not a room candidate."""
import bpy,json,hashlib
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree
r=Path('/jarvis/project/robomituba');base=r/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full';ref=r/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';out=ref/'ceramic_reflection_diagnostic_r59';assert not out.exists();out.mkdir();source=base/'scene_candidate_r59.blend';sha=hashlib.sha256(source.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(source));bpy.context.view_layer.update();deps=bpy.context.evaluated_depsgraph_get();v=next(v for v in json.loads((base/'review_views_fine_r45.json').read_text()) if v['name']=='ceramic_glaze_detail');v.update(render_width=1280,samples=48);camera=Vector(v['location']);target=Vector(v['target']);hits=[]
for offset in [-.1,-.2,0]:
 direction=(target+Vector((0,0,offset))-camera).normalized()
 for o in bpy.data.objects:
  if o.type!='MESH' or not o.get('program_key','').endswith('_wc'):continue
  ev=o.evaluated_get(deps);me=ev.to_mesh();tree=BVHTree.FromPolygons([o.matrix_world@p.co for p in me.vertices],[list(f.vertices) for f in me.polygons]);hit,normal,index,distance=tree.ray_cast(camera,direction,10);ev.to_mesh_clear()
  if hit is not None:hits.append((offset,distance,o,hit,normal))
assert hits;selected=None
for offset,distance,o,hit,normal in sorted(hits,key=lambda h:(abs(h[0]+.1),h[1])):
 toward_camera=(camera-hit).normalized()
 if normal.dot(toward_camera)<0:normal=-normal
 reflected=(2*normal.dot(toward_camera)*normal-toward_camera).normalized()
 for radius in [.6,.4,.25]:
  location=hit+reflected*radius;origin=hit+normal*.003;ray=location-origin;blocked=bpy.context.scene.ray_cast(deps,origin,ray.normalized(),distance=ray.length-.002)[0]
  if not blocked:selected=(o,hit,normal,reflected,location);break
 if selected:break
assert selected,'No unoccluded diagnostic reflected-light path';o,hit,normal,reflected,location=selected
materials=[]
for m in o.data.materials:
 if m and m.use_nodes:
  for bs in m.node_tree.nodes:
   if bs.type=='BSDF_PRINCIPLED':materials.append({'material':m.name,'roughness_linked':bs.inputs['Roughness'].is_linked,'roughness_default':bs.inputs['Roughness'].default_value,'ior':bs.inputs['IOR'].default_value,'metallic':bs.inputs['Metallic'].default_value,'normal_linked':bs.inputs['Normal'].is_linked})
data=bpy.data.lights.new('Diagnostic_reflection_strip','AREA');data.shape='RECTANGLE';data.size=.12;data.size_y=.40;data.energy=30;light=bpy.data.objects.new(data.name,data);bpy.context.scene.collection.objects.link(light);light.location=location;light.rotation_euler=(hit-location).to_track_quat('-Z','Y').to_euler();bpy.ops.wm.save_as_mainfile(filepath=str(out/'light_only.blend'));assert hashlib.sha256(source.read_bytes()).hexdigest()==sha;(out/'views.json').write_text(json.dumps([v],indent=2));(out/'experiment.json').write_text(json.dumps({'source':str(source),'source_sha256':sha,'target_object':o.name,'hit_point':list(hit),'geometric_normal':list(normal),'light_location':list(location),'path_unoccluded':True,'material_inventory':materials,'change':'one30W0.12x0.40m area only at reflected direction; mesh/material/camera/exposure unchanged','limits':'geometric normal approximates smooth shading normal; diagnostic floating light not final fixture installation','visual_acceptance':False},indent=2));print(out,flush=True)
