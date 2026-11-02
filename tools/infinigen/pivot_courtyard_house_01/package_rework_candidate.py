"""Audit scene geometry and pack the reviewed candidate into one Blender file."""
import argparse,json,math,socket,hashlib
from array import array
from pathlib import Path
import bpy

p=argparse.ArgumentParser();p.add_argument('blend');p.add_argument('--out',required=True);p.add_argument('--render-device',default='CPU');p.add_argument('--views');p.add_argument('--plan',required=True);p.add_argument('--quality',required=True);p.add_argument('--review');a=p.parse_args()
bpy.ops.wm.open_mainfile(filepath=a.blend)
invalid=[];beds={};nonfinite_vertices=[];vertex_count=0
invalid_transforms=[];invalid_curves=[];curve_points_checked=0
for o in bpy.data.objects:
 if any(not math.isfinite(v) for row in o.matrix_world for v in row):invalid_transforms.append(o.name)
 if o.type=='CURVE':
  bad=not math.isfinite(o.data.bevel_depth) or o.data.bevel_depth<0
  for spline in o.data.splines:
   for point in spline.bezier_points:
    curve_points_checked+=1
    bad=bad or any(not math.isfinite(v) for v in [*point.co,*point.handle_left,*point.handle_right,point.radius]) or point.radius<0
   for point in spline.points:
    curve_points_checked+=1
    bad=bad or any(not math.isfinite(v) for v in [*point.co,point.radius]) or point.radius<0
  if bad:invalid_curves.append(o.name)
 if o.type!='MESH':continue
 if any(not math.isfinite(v) or abs(v)>100 for v in o.dimensions):invalid.append(o.name)
 raw=array('f',[0.0])*(len(o.data.vertices)*3)
 o.data.vertices.foreach_get('co',raw);vertex_count+=len(o.data.vertices)
 if any(not math.isfinite(v) for v in raw):nonfinite_vertices.append(o.name)
 if 'BedFactory(' in o.name:
  beds.setdefault(o.get('ir_room','unknown'),[]).append({'name':o.name,'dimensions_m':list(o.dimensions)})
assert not invalid,invalid
assert not nonfinite_vertices,nonfinite_vertices
assert not invalid_transforms,invalid_transforms
assert not invalid_curves,invalid_curves
assert len(beds)==5 and all(len(v)==1 for v in beds.values()),beds
floors=[o.name for o in bpy.data.objects if o.name.endswith('.floor')]
plan=json.loads(Path(a.plan).read_text());expected_floors={name+'.floor' for name in plan['rooms']};assert set(floors)==expected_floors,{'missing':sorted(expected_floors-set(floors)),'extra':sorted(set(floors)-expected_floors)}
quality=json.loads(Path(a.quality).read_text())
source_sha=hashlib.sha256(Path(a.blend).read_bytes()).hexdigest()
review_valid=False
if a.review:
 review=json.loads(Path(a.review).read_text());expected={v['name'] for v in json.loads(Path(a.views).read_text())};findings=review.get('findings',[])
 review_valid=(review.get('status')=='all_views_accepted' and review.get('source_sha256')==source_sha and len(findings)==len(expected) and {v['space'] for v in findings}==expected and all(v.get('view_verdict') in ('pass','regression_pass') for v in findings))
requested_visual_acceptance=quality.get('status')=='accepted' or quality.get('visual_review_status')=='accepted'
if requested_visual_acceptance:assert review_valid,'Accepted packaging requires complete direct review of this exact source scene'
visual_accepted=requested_visual_acceptance and review_valid and all(g.get('status')=='pass' for v in quality['views'].values() for g in v['mandatory_gates'])
bpy.ops.file.pack_all()
missing=[]
for im in bpy.data.images:
 if im.source=='FILE' and not im.packed_file and im.filepath and not Path(bpy.path.abspath(im.filepath)).is_file():missing.append(im.filepath)
assert not missing,missing
window_lights=0
for o in bpy.data.objects:
 if o.type=='LIGHT' and o.data.type=='AREA' and o.parent and 'Window' in o.parent.name:
  area=o.data.size*(o.data.size_y if o.data.shape in ('RECTANGLE','ELLIPSE') else o.data.size)
  o.data.energy=80*max(area,.1);window_lights+=1
bpy.context.scene.cycles.use_denoising=True
bpy.context.scene.cycles.use_adaptive_sampling=True
if a.views:
 from mathutils import Vector
 views=json.loads(Path(a.views).read_text())
 v=next(v for v in views if v['name']=='living_reference_wide')
 camera_data=bpy.data.cameras.new('PivotReviewedCamera')
 camera=bpy.data.objects.new(camera_data.name,camera_data);bpy.context.scene.collection.objects.link(camera)
 camera.location=v['location'];camera.rotation_euler=(Vector(v['target'])-camera.location).to_track_quat('-Z','Y').to_euler()
 camera_data.angle=math.radians(v.get('hfov',85));camera_data.clip_start=.05;camera_data.clip_end=300
 bpy.context.scene.camera=camera;bpy.context.scene.render.engine='CYCLES';bpy.context.scene.cycles.device='CPU'
 bpy.context.scene.cycles.samples=96;bpy.context.scene.render.resolution_x=1536;bpy.context.scene.render.resolution_y=1152
bpy.context.scene['pivot_candidate_status']='visually accepted reconstruction candidate' if visual_accepted else 'work in progress; geometry packed; visual acceptance not achieved'
bpy.ops.wm.save_as_mainfile(filepath=a.out,compress=True)
Path(a.out).with_suffix('.audit.json').write_text(json.dumps({'hostname':socket.gethostname(),'packaging_device':'CPU','render_validation_device':a.render_device,
 'visual_accepted':visual_accepted,'authored_plan':a.plan,'expected_floor_names':sorted(expected_floors),'room_floor_count':len(floors),'bedrooms':beds,'invalid_mesh_dimensions':invalid,'nonfinite_vertex_meshes':nonfinite_vertices,'raw_vertices_checked':vertex_count,
 'raw_vertex_count_includes_shared_mesh_instances':True,'invalid_object_transforms':invalid_transforms,'invalid_curve_objects':invalid_curves,'curve_control_points_checked':curve_points_checked,
 'missing_external_images':missing,'packed_image_count':sum(bool(im.packed_file) for im in bpy.data.images),
 'source_scene':a.blend,'source_sha256':source_sha,'direct_review_record':a.review,'complete_direct_review_verified':review_valid,'candidate':a.out,'candidate_sha256':hashlib.sha256(Path(a.out).read_bytes()).hexdigest(),'window_area_lights_persisted':window_lights,'status':'candidate, not dataset promoted'},indent=2))
print('PIVOT_CANDIDATE_PACKED',a.out,flush=True)
