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
 c.type='ORTHO';c.ortho_scale=30
 cam.location=(13.25,11.5,45);cam.rotation_euler=(0,0,0)
 cam.rotation_euler=(Vector((13.25,11.5,0))-cam.location).to_track_quat('-Z','Y').to_euler()
 s.render.resolution_x=960*a.scale;s.render.resolution_y=864*a.scale;s.render.filepath=str(a.out/'overview.png')
 bpy.ops.render.render(write_still=True);print('PREVIEW overview CPU',flush=True)
else:
 views=json.loads(a.views.read_text());names=set(a.names.split(',')) if a.names else None
 views=[v for v in views if not names or v['name'] in names]
 if a.limit:views=views[:a.limit]
 for v in views:
  cam.location=v['location'];cam.rotation_euler=(Vector(v['target'])-cam.location).to_track_quat('-Z','Y').to_euler()
  c.angle=math.radians(v.get('hfov',70));s.render.resolution_x=512*a.scale;s.render.resolution_y=384*a.scale
  s.render.filepath=str(a.out/(v['name']+'.png'));bpy.ops.render.render(write_still=True)
  print('PREVIEW',v['name'],a.device,flush=True)
