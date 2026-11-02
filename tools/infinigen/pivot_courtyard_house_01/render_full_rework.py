"""Cycles previews with explicit CPU or allocated GPU selection.

Run with bundled Blender: --background SCENE --python render_preview.py --
--views views.json --out DIR [--limit N]. GPU mode requires an explicit CUDA_VISIBLE_DEVICES allocation.
"""
import argparse
import json
import math
import os
from pathlib import Path
import sys
import bpy
from mathutils import Vector

args=sys.argv[sys.argv.index('--')+1:]
p=argparse.ArgumentParser();p.add_argument('--views',type=Path);p.add_argument('--out',type=Path,required=True)
p.add_argument('--limit',type=int,default=0);p.add_argument('--names',default='');p.add_argument('--overview',action='store_true')
p.add_argument('--device',choices=['CPU','OPTIX'],default='CPU')
p.add_argument('--scale',type=int,default=1)
p.add_argument('--samples',type=int,default=24);a=p.parse_args(args)
a.out.mkdir(parents=True,exist_ok=True)
s=bpy.context.scene;s.render.engine='CYCLES';s.cycles.device='CPU';s.cycles.samples=a.samples
if a.device=='OPTIX':
 assert os.environ.get('CUDA_VISIBLE_DEVICES'), 'Explicit allocated CUDA_VISIBLE_DEVICES required'
 prefs=bpy.context.preferences.addons['cycles'].preferences
 prefs.compute_device_type='OPTIX';prefs.get_devices()
 selected=[]
 for device in prefs.devices:
  device.use=device.type=='OPTIX'
  if device.use:selected.append(device.name)
 assert selected,'No OptiX GPU visible'
 s.cycles.device='GPU'
 print('ALLOCATED_GPU',os.environ['CUDA_VISIBLE_DEVICES'],selected,flush=True)
s.cycles.use_denoising=True;s.cycles.use_adaptive_sampling=True
s.render.threads_mode='FIXED';s.render.threads=8;s.render.resolution_percentage=100
s.render.image_settings.file_format='PNG';s.render.use_persistent_data=True
c=bpy.data.cameras.new('pivot_direct_preview');cam=bpy.data.objects.new(c.name,c)
s.collection.objects.link(cam);s.camera=cam;c.clip_start=.05;c.clip_end=300;c.sensor_fit='HORIZONTAL'
for o in bpy.data.objects:
 if o.type=='LIGHT' and o.data.type=='AREA' and o.parent and 'Window' in o.parent.name:
  ar=o.data.size*(o.data.size_y if o.data.shape in ('RECTANGLE','ELLIPSE') else o.data.size)
  o.data.energy=80*max(ar,.1)
if a.overview:
 for o in bpy.data.objects:
  if o.name.endswith(('.ceiling','.exterior')) or o.get('pivot_roof'):o.hide_render=True
 if not s.world:s.world=bpy.data.worlds.new('pivot_overview_world')
 s.world.use_nodes=True
 bg=s.world.node_tree.nodes.get('Background')
 if bg:bg.inputs['Color'].default_value=(.8,.8,.8,1);bg.inputs['Strength'].default_value=.8
 c.type='ORTHO'
 corners=[o.matrix_world@Vector(v) for o in bpy.data.objects if o.type=='MESH' and (o.name.endswith('.floor') or o.name.startswith(('PivotGarageV22_driveway_apron','PivotGarageV17_external_walk','PivotEntryDeckPlankFactory','PivotMainDeckPlankFactory'))) for v in o.bound_box]
 assert corners,'No room floors available for overview framing'
 xmin,xmax=min(v.x for v in corners),max(v.x for v in corners)
 ymin,ymax=min(v.y for v in corners),max(v.y for v in corners)
 center=Vector(((xmin+xmax)/2,(ymin+ymax)/2,0))
 c.ortho_scale=max(xmax-xmin,(ymax-ymin)*960/864)*1.12
 cam.location=center+Vector((0,0,45));cam.rotation_euler=(center-cam.location).to_track_quat('-Z','Y').to_euler()
 print('OVERVIEW_FLOOR_BOUNDS',[xmin,xmax,ymin,ymax],'ORTHO',c.ortho_scale,flush=True)
 s.render.resolution_x=960*a.scale;s.render.resolution_y=864*a.scale;s.render.filepath=str(a.out/'overview.png')
 bpy.ops.render.render(write_still=True);print('PREVIEW overview',a.device,flush=True)
else:
 views=json.loads(a.views.read_text());names=set(a.names.split(',')) if a.names else None
 views=[v for v in views if not names or v['name'] in names]
 if a.limit:views=views[:a.limit]
 import datetime,hashlib,socket
 progress_path=a.out.parents[1]/'full_rework_render_progress.json'
 def digest(path):
  h=hashlib.sha256()
  with open(path,'rb') as handle:
   for block in iter(lambda:handle.read(4*1024*1024),b''):h.update(block)
  return h.hexdigest()
 progress={'phase':'rendering','source_scene':bpy.data.filepath,'source_sha256':digest(bpy.data.filepath),'camera_manifest':str(a.views),'total':len(views),'completed':[],'device':a.device,'cuda_visible_devices':os.environ.get('CUDA_VISIBLE_DEVICES'),'hostname':socket.gethostname(),'pid':os.getpid(),'python':sys.executable,'blender':bpy.app.version_string,'started_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'visual_acceptance':'not implied by rendering'}
 def save_progress():
  progress['updated_at']=datetime.datetime.now(datetime.timezone.utc).isoformat();tmp=progress_path.with_suffix('.tmp');tmp.write_text(json.dumps(progress,ensure_ascii=False,indent=2)+'\n');tmp.replace(progress_path)
 save_progress()
 for v in views:
  cam.location=v['location'];cam.rotation_euler=(Vector(v['target'])-cam.location).to_track_quat('-Z','Y').to_euler()
  c.angle=math.radians(v.get('hfov',70));s.render.resolution_x=512*a.scale;s.render.resolution_y=384*a.scale
  s.render.filepath=str(a.out/(v['name']+'.png'));bpy.ops.render.render(write_still=True)
  print('PREVIEW',v['name'],a.device,flush=True)
  path=a.out/(v['name']+'.png');progress['completed'].append({'name':v['name'],'path':str(path),'sha256':digest(path),'width':s.render.resolution_x,'height':s.render.resolution_y,'samples':a.samples,'visual_review':'pending'})
  if len(progress['completed'])==progress['total']:progress['phase']='rendered_all_visual_review_pending'
  save_progress()
  import runpy
  runpy.run_path(str(Path(__file__).with_name('build_progress_dashboard.py')),run_name='__main__')

