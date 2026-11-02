"""Replace procedural garment approximations with native Infinigen shirts and gravity drape."""
import bpy,sys,json,math,hashlib,random
from pathlib import Path
from mathutils import Vector
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT/'tools/infinigen'));sys.path.insert(0,str(ROOT/'modules/infinigen'))
from room_planner import proc_assets as pa
base=ROOT/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full';ref=ROOT/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';source=base/'scene_candidate_r26.blend';out=base/'scene_candidate_r27.blend';assert not out.exists();before=hashlib.sha256(source.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(source));prototypes=[]
for i in range(3):
 o=pa._cloth('shirt','ShirtFactory',791120+i,width=.28,size=.58,sleeve_width=.075,sleeve_length=.07,thickness=.002)
 assert o is not None,'Native ShirtFactory unavailable; do not substitute primitives'
 o.rotation_euler=(math.pi/2,0,0);o.location=(0,0,0);prototypes.append(o);print('NATIVE_GARMENT_GENERATED',i,len(o.data.polygons),flush=True)
pa._drape(prototypes,pin_fn=lambda z,zmax:z>zmax-.075,frames=36);print('NATIVE_GARMENT_DRAPE_FINISHED',flush=True)
removed=[]
for o in list(bpy.data.objects):
 key=o.get('program_key','')
 if any(t in key for t in ('_hanging_garment_','_sleeve_','_hem_')):removed.append(o.name);bpy.data.objects.remove(o,do_unlink=True)
records=[]
for unit in (101,102):
 parent=next(o for o in bpy.data.objects if o.get('program_key')==str(unit)+'_dressing');rng=random.Random(unit+8100)
 for tier,railz in enumerate((1.8,1.05)):
  for g in range(6):
   proto=prototypes[(g+tier)%3];o=proto.copy();o.data=proto.data.copy();bpy.context.scene.collection.objects.link(o);xs=[v.co.x for v in o.data.vertices];ys=[v.co.y for v in o.data.vertices];zs=[v.co.z for v in o.data.vertices];factor=min(1,.48/(max(xs)-min(xs)),.65/(max(zs)-min(zs)));centerx=(max(xs)+min(xs))/2;centery=(max(ys)+min(ys))/2;top=max(zs)
   for v in o.data.vertices:v.co=Vector(((v.co.x-centerx)*factor,(v.co.y-centery)*factor,(v.co.z-top)*factor))
   o.parent=parent;o.matrix_parent_inverse.identity();o.location=(.28,-1.04+g*.22,railz-.055);o.rotation_euler=(0,0,rng.uniform(-.16,.16));o.scale=(1,1,1);o.name=f'FineR3_{unit}_native_shirt_{tier}_{g}';o.data.materials.clear();o.data.materials.append(bpy.data.materials['FineR1_garment_'+str((g+tier+unit)%5)]);o['reference_scene_owner']='dual_unit_residential_floor_03';o['program_key']=f'{unit}_native_garment_{tier}_{g}';o['audit_kind']='detail';o['infinigen_factory']='ShirtFactory';o['gravity_drape_frames']=36;records.append({'object':o.name,'native_polygons':len(o.data.polygons),'uniform_fit_scale':factor})
for o in prototypes:bpy.data.objects.remove(o,do_unlink=True)
bpy.context.view_layer.update();bpy.ops.wm.save_as_mainfile(filepath=str(out));assert hashlib.sha256(source.read_bytes()).hexdigest()==before;(ref/'realism_refinement_r27.json').write_text(json.dumps({'source':str(source),'source_sha256':before,'candidate':str(out),'reason':'Procedural r24/r26 shirts retained rigid/inflated or regular corrugated silhouettes; native factory plus actual gravity settlement used instead.','factory':'infinigen.assets.objects.clothes.shirt.ShirtFactory','prototype_seeds':[791120,791121,791122],'cloth_solver':'Existing room_planner.proc_assets._drape,36frames, shoulder pins','removed_procedural_objects':len(removed),'garments':records,'photorealism_accepted':False,'requires':'Rendered visual review; prototype reuse and seam detail still assessed explicitly.'},indent=2));print('SAVED_NATIVE_GARMENT_CANDIDATE',str(out),flush=True)
