"""Native Infinigen pressure pillow with60mm initial side gusset;no post-solve panel correction."""
import bpy,sys,json,os,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT/'modules/infinigen'))
from infinigen.assets.objects.seating.pillow import PillowFactory
ref=ROOT/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';out=ref/'native_pillow_gusset06.blend';assert not out.exists();bpy.ops.wm.read_factory_settings(use_empty=True);rows=[]
for i,(width,size) in enumerate([(.64,.42)]):
 seed=842111+i;fac=PillowFactory(seed);fac.shape='rectangle';fac.width=width;fac.size=size;fac.thickness=.06;fac.extrude_thickness=0;fac.has_seam=False
 o=fac.spawn_asset(seed);o.name='NativePressurePillow_'+str(i);o['infinigen_factory']='PillowFactory';o['factory_seed']=seed;o['factory_width_m']=width;o['factory_size_m']=size
 bpy.context.view_layer.update();dg=bpy.context.evaluated_depsgraph_get();ev=o.evaluated_get(dg);mesh=ev.to_mesh();lo=[min(v.co[k] for v in mesh.vertices) for k in range(3)];hi=[max(v.co[k] for v in mesh.vertices) for k in range(3)];rows.append({'object':o.name,'seed':seed,'factory_parameters':{'shape':'rectangle','width':width,'size':size,'thickness':.06,'extrude_thickness':0,'has_seam':False},'evaluated_bounds':[lo,hi],'dimensions':[hi[k]-lo[k] for k in range(3)],'vertices':len(mesh.vertices),'polygons':len(mesh.polygons)});ev.to_mesh_clear();print('NATIVE_PILLOW',json.dumps(rows[-1]),flush=True)
 (ref/'native_pillow_gusset06_job.json').write_text(json.dumps({'pid':os.getpid(),'phase':'building','prototypes':rows},indent=2))
bpy.ops.wm.save_as_mainfile(filepath=str(out));(ref/'native_pillow_gusset06_job.json').write_text(json.dumps({'pid':os.getpid(),'phase':'prototypes_saved','blend':str(out),'sha256':hashlib.sha256(out.read_bytes()).hexdigest(),'prototypes':rows,'photorealism_accepted':False,'requires':'placement/contact/material and direct scene comparison'},indent=2));print('SAVED',out,flush=True)
