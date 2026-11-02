"""Bowed/cupped native leaf blades with restrained pigment;no room modification."""
import bpy,json,numpy as np
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];base=ROOT/'data/venue_refs/floor_plans_v3/commercial_office_floor_02/assembled_leaf_plant_studio';out=base/'plant03.blend';assert not out.exists();bpy.ops.wm.open_mainfile(filepath=str(base/'plant02.blend'))
parts=sorted([o for o in bpy.data.objects if o.name.startswith('Indoor_leaf_')],key=lambda o:o.name);original=parts[0].data;m=original.materials[0].copy();m.name='Indoor_leaf_deeper_pigment'
node=next(n for n in m.node_tree.nodes if n.type=='VECT_MATH' and n.operation=='MULTIPLY' and tuple(round(v,2) for v in n.inputs[1].default_value)==(.28,.42,.24));node.inputs[1].default_value=(.08,.14,.06)
rows=[]
for o,factor in zip(parts,[.8,1.1,.65,1.2,.9,1.05,.75]):
 mesh=original.copy();o.data=mesh;mesh.materials[0]=m;a=np.empty(len(mesh.vertices)*3,dtype=np.float32);mesh.vertices.foreach_get('co',a);a=a.reshape(-1,3);before=a.copy();upper=a[:,2]>.55;_,axes=np.linalg.eigh(np.cov(a[upper,:2].T));width=axes[:,1];normal=np.array([-width[1],width[0]]);w=a[:,:2]@width;half=max(abs(w[upper]));t=np.clip((a[:,2]-.55)/.45,0,1);wave=np.sin(np.pi*t)
 a[:,:2]+=((.035*factor+.008*(w/max(half,1e-6))**2)*wave)[:,None]*normal
 theta=.25*factor*t;cs=np.cos(theta);sn=np.sin(theta);x=a[:,0].copy();y=a[:,1].copy();a[:,0]=cs*x-sn*y;a[:,1]=sn*x+cs*y;a[:,2]-=.025*factor*t*t
 mesh.vertices.foreach_set('co',a.ravel());mesh.update();rows.append({'object':o.name,'maximum_normalized_vertex_shift':float(np.linalg.norm(a-before,axis=1).max()),'blade_bow_factor':factor})
bpy.ops.wm.save_as_mainfile(filepath=str(out));(base/'refinement03.json').write_text(json.dumps({'source':'plant02.blend','candidate':str(out),'changes':['Blade-only longitudinal bow,cross-blade cupping andmodest twist;petioles/root coordinates retained','Per-leaf deformation variation','Pigment gain RGB(.08,.14,.06) rather than(.28,.42,.24),same lighting/exposure/native shader response'],'parts':rows,'photorealism_accepted':False,'requires':'Actual same studio render;reject crushed veins,facets,black foliage or unnatural leaf curl'},indent=2));print('SAVED',out,flush=True)
