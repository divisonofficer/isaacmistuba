"""CPU-only pkg_c copy/render verification; run under shared blender_test.lock."""
import argparse,json,math,os,sys
from pathlib import Path
import bpy
from mathutils import Vector
sys.path.insert(0,str(Path(__file__).resolve().parent))
import ratio1_common as rc
import ratio1_plants,ratio1_checkout
ap=argparse.ArgumentParser();ap.add_argument('--tag',choices=['S37','S38','S39'],required=True);ap.add_argument('--out',required=True)
a=ap.parse_args(sys.argv[sys.argv.index('--')+1:]);out=Path(a.out);out.mkdir(parents=True,exist_ok=True)
os.environ['RATIO1_PLANTS']=os.environ['RATIO1_CHECKOUT']='1'
stats={};ratio1_plants.apply(stats,a.tag);ratio1_checkout.apply(stats,a.tag)
s=bpy.context.scene;s.render.engine='CYCLES';s.cycles.device='CPU';s.cycles.samples=24;s.cycles.use_denoising=True
s.render.resolution_x=640;s.render.resolution_y=480;s.render.resolution_percentage=100;s.render.threads_mode='FIXED';s.render.threads=8
s.render.image_settings.file_format='PNG';s.render.image_settings.color_mode='RGB'
cam=bpy.data.objects.new('PkgCCamera',bpy.data.cameras.new('PkgCCamera'));s.collection.objects.link(cam);s.camera=cam;cam.data.lens=38;cam.data.clip_start=.05
objects=[o for o in s.objects if o.name.startswith('PkgCProp_')];packs=[o for o in objects if o.get('pkg_c_kind')=='pack']
poses=[]
if a.tag=='S37':
 pts=[Vector(rc.bb(o)[0])+Vector(rc.bb(o)[1]) for o in packs];c=sum(pts,Vector())/(2*len(pts))
 cs=[o for o in s.objects if o.name.startswith('CheckoutCounterFactory')];lo,hi=rc.bb(cs[0]);along_x=hi[0]-lo[0]>=hi[1]-lo[1]
 # Approach from shop interior, opposite the nearest boundary wall.
 floor=next(o for o in s.objects if o.name.endswith('.floor'));fl,fh=rc.bb(floor);fc=Vector(((fl[0]+fh[0])/2,(fl[1]+fh[1])/2,c.z))
 direction=(fc-c);direction.z=0;direction.normalize()
 poses.append(('S37_checkout',c+direction*2.1+Vector((0,0,1.45)),c))
 shrub=s.objects.get('PkgCPlant_S37Shrub0');lo,hi=rc.bb(shrub);c2=(Vector(lo)+Vector(hi))/2
 poses.append(('S37_entrance',c2+(fc-c2).normalized()*2.6+Vector((0,0,.4)),c2))
elif a.tag=='S38':
 gs=[o for o in objects if o.get('pkg_c_kind')=='gift'];c=sum(((Vector(rc.bb(o)[0])+Vector(rc.bb(o)[1]))/2 for o in gs[:6]),Vector())/6
 poses.append(('S38_gifts',c+Vector((2.2,-2.2,1.25)),c))
else:
 o=s.objects.get('PkgCPlant_S39Shrub');lo,hi=rc.bb(o);c=(Vector(lo)+Vector(hi))/2
 floor=next(o for o in s.objects if o.name.endswith('.floor'));fl,fh=rc.bb(floor);fc=Vector(((fl[0]+fh[0])/2,(fl[1]+fh[1])/2,c.z))
 poses.append(('S39_plants',c+(fc-c).normalized()*2.8+Vector((0,0,.25)),c))
# Save only to an explicit output copy, never input source.
s.render.filepath=str(out/(a.tag+'.png'))
bpy.ops.wm.save_as_mainfile(filepath=str(out/(a.tag+'_pkg_c.blend')))
for i,o in enumerate(packs):o.pass_index=i+1
if packs:
 s.use_nodes=True;nt=s.node_tree;nt.nodes.clear();rl=nt.nodes.new('CompositorNodeRLayers');s.view_layers[0].use_pass_object_index=True
 composite=nt.nodes.new('CompositorNodeComposite');nt.links.new(rl.outputs['Image'],composite.inputs[0])
 for i,o in enumerate(packs):
  mask=nt.nodes.new('CompositorNodeIDMask');mask.index=i+1;mask.use_antialiasing=True;nt.links.new(rl.outputs['IndexOB'],mask.inputs[0])
  fo=nt.nodes.new('CompositorNodeOutputFile');fo.base_path=str(out/'masks');fo.format.file_format='PNG';fo.format.color_mode='BW';fo.file_slots[0].path=o.name+'_';nt.links.new(mask.outputs[0],fo.inputs[0])
for name,loc,target in poses:
 cam.location=loc;cam.rotation_euler=(target-loc).to_track_quat('-Z','Y').to_euler();s.render.filepath=str(out/(name+'.png'))
 bpy.ops.render.render(write_still=True)
 if packs:break # mask verification is for the checkout pose; entrance separately below
if a.tag=='S37':
 s.use_nodes=False
 name,loc,target=poses[1];cam.location=loc;cam.rotation_euler=(target-loc).to_track_quat('-Z','Y').to_euler();s.render.filepath=str(out/(name+'.png'));bpy.ops.render.render(write_still=True)
(out/'receipt.json').write_text(json.dumps({'tag':a.tag,'stats':stats,'pack_objects':len(packs),'poses':[{ 'name':n,'location':list(l),'target':list(t)} for n,l,t in poses]},indent=2))
