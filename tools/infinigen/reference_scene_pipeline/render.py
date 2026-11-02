"""Fixed-camera CPU/GPU render with per-frame receipts; never edits source."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import bpy
from mathutils import Vector

ap=argparse.ArgumentParser();ap.add_argument('--views',type=Path,required=True)
ap.add_argument('--out',type=Path,required=True);ap.add_argument('--samples',type=int,default=16)
ap.add_argument('--device',choices=['CPU','OPTIX'],default='CPU');ap.add_argument('--names',default='')
ap.add_argument('--width',type=int,default=640)
ap.add_argument('--overview-width',type=int,default=0)
ap.add_argument('--threads',type=int,default=8)
ap.add_argument('--no-denoise',action='store_true',help='Preserve microstructure for paired diagnostic tests; noise is not surface evidence')
ap.add_argument('--bathroom-review',action='store_true',help='Paired narrow bathroom reflection sources, diagnostic only')
ap.add_argument('--material-review',action='store_true',help='Deterministic grazing lights for diagnostic A/B only')
ap.add_argument('--preserve-source-lighting',action='store_true',help='Keep authored world and window-light energy instead of legacy reference overrides')
a=ap.parse_args(sys.argv[sys.argv.index('--')+1:]);a.out.mkdir(parents=True,exist_ok=True);assert 1<=a.threads<=64,'threads must be within1..64'
s=bpy.context.scene;s.render.engine='CYCLES';s.cycles.device='CPU';s.cycles.samples=a.samples
s.cycles.use_denoising=not a.no_denoise;s.render.threads_mode='FIXED';s.render.threads=a.threads
if a.device=='OPTIX':
    assert os.environ.get('CUDA_VISIBLE_DEVICES'),'GPU allocation must be explicit'
    prefs=bpy.context.preferences.addons['cycles'].preferences;prefs.compute_device_type='OPTIX';prefs.get_devices()
    for d in prefs.devices:d.use=d.type=='OPTIX'
    assert any(d.use for d in prefs.devices);s.cycles.device='GPU'
world=s.world or bpy.data.worlds.new('reference_daylight');s.world=world;world.use_nodes=True
bg=world.node_tree.nodes.get('Background')
lighting_overrides=[]
if bg and not a.preserve_source_lighting:
    before=bg.inputs['Strength'].default_value
    bg.inputs['Strength'].default_value=.45
    lighting_overrides.append({'kind':'world_background_strength','node':bg.name,'before':before,'after':.45})
s.view_settings.view_transform='AgX';s.view_settings.exposure=0
s.render.resolution_x=a.width;s.render.resolution_y=a.width*3//4;s.render.resolution_percentage=100
s.render.image_settings.file_format='PNG';s.render.use_persistent_data=True
if a.material_review:
    for index,(loc,target,power,size) in enumerate([
        ((8.0,11.7,.45),(8.7,10.8,.12),35,.45),
        ((6.0,10.8,1.05),(6.0,11.6,.85),18,.4),
        ((9.6,7.8,1.9),(9.89,7.3,1.45),18,.3),
        ((13.5,5,1.45),(14.22,4.65,1),30,.35),
        ((5.3,2.3,.55),(5.2,1.6,.13),22,.5)]):
        light=bpy.data.lights.new(f'material_diagnostic_{index}','AREA');light.energy=power;light.shape='DISK';light.size=size
        obj=bpy.data.objects.new(light.name,light);s.collection.objects.link(obj);obj.location=loc
        obj.rotation_euler=(Vector(target)-obj.location).to_track_quat('-Z','Y').to_euler()
if a.bathroom_review:
    for index,(loc,target,power,size) in enumerate([((2.65,5.2,2.35),(.25,5.45,1.1),25,.22),((.32,3.9,1.7),(1.8,4.4,1.1),6,.18),((1.7,4.55,2.5),(2.0,4.1,.2),20,.15)]):
        light=bpy.data.lights.new(f'bathroom_reflection_diagnostic_{index}','AREA');light.energy=power;light.shape='DISK';light.size=size
        obj=bpy.data.objects.new(light.name,light);s.collection.objects.link(obj);obj.location=loc;obj.rotation_euler=(Vector(target)-obj.location).to_track_quat('-Z','Y').to_euler()
data=bpy.data.cameras.new('reference_camera');cam=bpy.data.objects.new(data.name,data);s.collection.objects.link(cam);s.camera=cam
data.clip_start=.05;data.clip_end=150
for o in bpy.data.objects:
    if not a.preserve_source_lighting and o.type=='LIGHT' and o.data.type=='AREA' and o.parent and 'Window' in o.parent.name:
        area=o.data.size*(o.data.size_y if o.data.shape=='RECTANGLE' else o.data.size)
        before=o.data.energy
        o.data.energy=65*max(area,.1)
        lighting_overrides.append({'kind':'window_area_energy','object':o.name,'parent':o.parent.name,'before':before,'after':o.data.energy})
hidden={o.name:o.hide_render for o in bpy.data.objects}
source=Path(bpy.data.filepath);digest=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
receipt={'source':str(source),'source_sha256':digest(source),'device':a.device,
         'lighting_policy':'authored' if a.preserve_source_lighting else 'legacy_reference_override','lighting_overrides':lighting_overrides,
         'cuda_visible_devices':os.environ.get('CUDA_VISIBLE_DEVICES'),'samples':a.samples,
         'diagnostic_grazing_lights':a.material_review,'bathroom_diagnostic_lights':a.bathroom_review,'denoising':not a.no_denoise,
         'visual_acceptance':False,'render_threads':a.threads,'renderer_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'frames':[]}
views=json.loads(a.views.read_text());names=set(a.names.split(',')) if a.names else None
for v in views:
    if names and v['name'] not in names:continue
    overview=v.get('overview',False)
    width=v.get('render_width',a.overview_width if overview and a.overview_width else a.width)
    s.cycles.samples=v.get('samples',a.samples)
    s.render.resolution_x=width;s.render.resolution_y=width*3//4
    for o in bpy.data.objects:
        o.hide_render=bool(hidden.get(o.name,False) or (overview and (o.name.endswith(('.ceiling','.exterior')) or o.name.startswith('Office02_linear_fixture') or o.get('reference_ceiling_detail',False))))
    data.type='ORTHO' if overview else 'PERSP'
    if overview:data.ortho_scale=v['ortho_scale']
    else:data.angle=math.radians(v.get('hfov',65))
    cam.location=v['location'];cam.rotation_euler=(Vector(v['target'])-cam.location).to_track_quat('-Z','Y').to_euler()
    path=a.out/(v['name']+'.png');s.render.filepath=str(path.resolve());bpy.ops.render.render(write_still=True)
    receipt['frames'].append({'name':v['name'],'path':str(path.resolve()),'sha256':digest(path),
                             'width':s.render.resolution_x,'height':s.render.resolution_y,'samples':s.cycles.samples,'camera':v})
    (a.out/'render_receipt.json').write_text(json.dumps(receipt,indent=2))
    print('REFERENCE_FRAME_COMPLETE',v['name'],flush=True)
receipt['phase']='rendered_visual_review_pending';receipt['source_unchanged']=digest(source)==receipt['source_sha256']
(a.out/'render_receipt.json').write_text(json.dumps(receipt,indent=2))
