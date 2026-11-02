"""Native Infinigen pressure-cloth pillows for replacing rounded-box cushions."""
import bpy,sys,json,os,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT/'modules/infinigen'))
from infinigen.assets.objects.seating.pillow import PillowFactory
from infinigen.assets.scatters import clothes
from mathutils import Vector
from mathutils.bvhtree import BVHTree
_original_cloth_sim=clothes.cloth_sim
controls={'tension_stiffness':15,'compression_stiffness':15,'shear_stiffness':10,'bending_stiffness':.3,'tension_stiffness_max':60,'compression_stiffness_max':60,'shear_stiffness_max':30,'bending_stiffness_max':5,'quality':12,'tension_damping':10,'compression_damping':10,'shear_damping':10,'bending_damping':3,'air_damping':5,'uniform_pressure_force':.8}
def seam_supported_sim(obj,*args,**kwargs):
 group=obj.vertex_groups.new(name='Sewn_perimeter_stiffness');hx=max(abs(v.co.x) for v in obj.data.vertices);hy=max(abs(v.co.y) for v in obj.data.vertices)
 for v in obj.data.vertices:
  distance=min(hx-abs(v.co.x),hy-abs(v.co.y));weight=max(0,min(1,(.018-distance)/.012))
  if weight:group.add([v.index],weight,'REPLACE')
 kwargs.update(controls);kwargs.update(vertex_group_structural_stiffness=group.name,vertex_group_shear_stiffness=group.name,vertex_group_bending=group.name)
 return _original_cloth_sim(obj,*args,**kwargs)
clothes.cloth_sim=seam_supported_sim
ref=ROOT/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';out=ref/'native_pillow_stiff_seam_prototypes.blend';assert not out.exists();bpy.ops.wm.read_factory_settings(use_empty=True);rows=[]
for i,(width,size) in enumerate([(.46,.40),(.64,.42)]):
 seed=842110+i;fac=PillowFactory(seed);fac.shape='rectangle';fac.width=width;fac.size=size;fac.thickness=.0065;fac.extrude_thickness=0;fac.has_seam=False
 o=fac.spawn_asset(seed);o.name='NativeStiffSeamPillow_'+str(i);o['infinigen_factory']='PillowFactory';o['factory_seed']=seed;o['factory_width_m']=width;o['factory_size_m']=size
 bpy.context.view_layer.update();dg=bpy.context.evaluated_depsgraph_get();ev=o.evaluated_get(dg);mesh=ev.to_mesh();lo=[min(v.co[k] for v in mesh.vertices) for k in range(3)];hi=[max(v.co[k] for v in mesh.vertices) for k in range(3)];rows.append({'object':o.name,'seed':seed,'factory_parameters':{'shape':'rectangle','width':width,'size':size,'thickness':.0065,'extrude_thickness':0,'has_seam':False},'evaluated_bounds':[lo,hi],'dimensions':[hi[k]-lo[k] for k in range(3)],'vertices':len(mesh.vertices),'polygons':len(mesh.polygons)});tree=BVHTree.FromPolygons([v.co for v in mesh.vertices],[list(f.vertices) for f in mesh.polygons]);recessions=[]
 for axis in [0,1]:
  for sign in [-1,1]:
   origin=Vector((0,0,0));origin[axis]=sign;direction=-origin;hit,_,_,_=tree.ray_cast(origin,direction,2);assert hit is not None;edge=hi[axis] if sign>0 else -lo[axis];recessions.append(edge-sign*hit[axis])
 rows[-1]['edge_midpoint_recession_m']=recessions;rows[-1]['gross_outline_gate_pass']=max(recessions)<.015;rows[-1]['cloth_controls']=controls
 ev.to_mesh_clear();print('NATIVE_PILLOW',json.dumps(rows[-1]),flush=True)
 (ref/'native_pillow_stiff_seam_prototypes_job.json').write_text(json.dumps({'pid':os.getpid(),'phase':'building','prototypes':rows},indent=2))
bpy.ops.wm.save_as_mainfile(filepath=str(out));(ref/'native_pillow_stiff_seam_prototypes_job.json').write_text(json.dumps({'pid':os.getpid(),'phase':'prototypes_saved','blend':str(out),'sha256':hashlib.sha256(out.read_bytes()).hexdigest(),'prototypes':rows,'photorealism_accepted':False,'requires':'gross_outline gate,placement/contact/material and direct scene comparison;no perimeter position pins used'},indent=2));print('SAVED',out,flush=True)
