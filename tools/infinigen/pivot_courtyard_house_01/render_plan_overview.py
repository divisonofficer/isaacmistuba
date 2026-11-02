"""Reopen a packed scene and render a legible full-site cutaway plan.

Only diagnostic camera, roof visibility and lighting are changed in memory.
The packed source file is never resaved.
"""
import argparse,datetime,hashlib,json,os,sys
from pathlib import Path
import bpy
from mathutils import Vector

p=argparse.ArgumentParser();p.add_argument('--out',type=Path,required=True);p.add_argument('--width',type=int,default=3840);p.add_argument('--height',type=int,default=2560);p.add_argument('--samples',type=int,default=64);p.add_argument('--exposure',type=float,default=-.5)
a=p.parse_args(sys.argv[sys.argv.index('--')+1:]);a.out.mkdir(parents=True,exist_ok=True)
assert not os.environ.get('CUDA_VISIBLE_DEVICES'),'This overview runner is explicitly CPU-only'
s=bpy.context.scene;s.render.engine='CYCLES';s.cycles.device='CPU';s.cycles.samples=a.samples;s.cycles.use_denoising=True;s.cycles.use_adaptive_sampling=True;s.render.threads_mode='FIXED';s.render.threads=8
hidden=[];window_fill=[]
for o in bpy.data.objects:
    if o.name.endswith(('.ceiling','.exterior')) or o.get('pivot_roof'):
        o.hide_render=True;hidden.append(o.name)
    if o.type=='LIGHT' and o.data.type=='AREA' and o.parent and 'Window' in o.parent.name:
        o.data=o.data.copy();o.data.energy=0;window_fill.append(o.name)
if not s.world:s.world=bpy.data.worlds.new('plan_overview_world')
s.world.use_nodes=True;bg=s.world.node_tree.nodes.get('Background')
if bg:bg.inputs['Color'].default_value=(.8,.8,.8,1);bg.inputs['Strength'].default_value=.5
s.view_settings.view_transform='AgX';s.view_settings.exposure=a.exposure
try:s.view_settings.look='AgX - Medium High Contrast'
except TypeError:pass
corners=[o.matrix_world@Vector(v) for o in bpy.data.objects if o.type=='MESH' and (o.name.endswith('.floor') or o.name.startswith(('PivotGarageV22_driveway_apron','PivotGarageV17_external_walk','PivotEntryDeckPlankFactory','PivotMainDeckPlankFactory'))) for v in o.bound_box]
assert corners
x0,x1=min(v.x for v in corners),max(v.x for v in corners);y0,y1=min(v.y for v in corners),max(v.y for v in corners);center=Vector(((x0+x1)/2,(y0+y1)/2,0))
c=bpy.data.cameras.new('PivotPlanOverviewCamera');c.type='ORTHO';c.sensor_fit='HORIZONTAL';c.clip_start=.05;c.clip_end=300;c.ortho_scale=max(x1-x0,(y1-y0)*a.width/a.height)*1.08
cam=bpy.data.objects.new(c.name,c);s.collection.objects.link(cam);cam.location=center+Vector((0,0,45));cam.rotation_euler=(center-cam.location).to_track_quat('-Z','Y').to_euler();s.camera=cam
s.render.resolution_x=a.width;s.render.resolution_y=a.height;s.render.resolution_percentage=100;s.render.image_settings.file_format='PNG';output=a.out/'overview.png';s.render.filepath=str(output)
print('PLAN_OVERVIEW_SETUP',bpy.data.filepath,[x0,x1,y0,y1],c.ortho_scale,a.width,a.height,s.view_settings.view_transform,s.view_settings.look,a.exposure,flush=True)
bpy.ops.render.render(write_still=True)
def sha(path):
    h=hashlib.sha256()
    with open(path,'rb') as f:
        for block in iter(lambda:f.read(4*1024*1024),b''):h.update(block)
    return h.hexdigest()
(a.out/'overview_provenance.json').write_text(json.dumps({'source_packed_scene':bpy.data.filepath,'source_sha256':sha(bpy.data.filepath),'render':str(output),'render_sha256':sha(output),'dimensions':[a.width,a.height],'samples':a.samples,'device':'CPU','floor_and_site_bounds':[x0,x1,y0,y1],'ortho_scale':c.ortho_scale,'diagnostic_setup':{'hidden_roof_and_outer_skins':hidden,'window_fill_lights_disabled':window_fill,'world_background_strength':.5,'view_transform':s.view_settings.view_transform,'look':s.view_settings.look,'exposure':a.exposure},'created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'scope':'Cutaway floorplan illustration; source geometry is unchanged and source file is not resaved.'},indent=2)+'\n')
print('PIVOT_PLAN_OVERVIEW_RENDERED',str(output),flush=True)
