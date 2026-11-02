"""Leaf-component assembly trial: credible petiole gauge and less neon native leaf response."""
import bpy,json,numpy as np
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];base=ROOT/'data/venue_refs/floor_plans_v3/commercial_office_floor_02/assembled_leaf_plant_studio'
out=base/'plant02.blend';assert not out.exists();bpy.ops.wm.open_mainfile(filepath=str(base/'plant.blend'))
parts=sorted([o for o in bpy.data.objects if o.name.startswith('Indoor_leaf_')],key=lambda o:o.name);mesh=parts[0].data
coords=np.empty(len(mesh.vertices)*3,dtype=np.float32);mesh.vertices.foreach_get('co',coords);coords=coords.reshape(-1,3)
before=coords.copy();z=coords[:,2];bins=np.floor(z*160).astype(int)
for band in np.unique(bins[z<.6]):
 idx=np.flatnonzero((bins==band)&(z<.6));center=np.median(coords[idx,:2],axis=0);t=np.clip((.6-z[idx])/.15,0,1);gain=1+2*(t*t*(3-2*t));coords[idx,:2]=center+(coords[idx,:2]-center)*gain[:,None]
mesh.vertices.foreach_set('co',coords.ravel());mesh.update()
old=mesh.materials[0];m=old.copy();m.name='Indoor_native_leaf_cuticle';mesh.materials[0]=m
nodes=m.node_tree.nodes;links=m.node_tree.links;group=next(n for n in nodes if n.type=='GROUP' and n.node_tree and 'leaf_shader' in n.node_tree.name)
prior=group.inputs['Color'].links[0].from_socket;gain=nodes.new('ShaderNodeVectorMath');gain.operation='MULTIPLY';gain.inputs[1].default_value=(.28,.42,.24);links.new(prior,gain.inputs[0]);links.new(gain.outputs[0],group.inputs['Color'])
group.node_tree=group.node_tree.copy()
for n in group.node_tree.nodes:
 if n.type in ['BSDF_GLOSSY','BSDF_ANISOTROPIC'] and 'Roughness' in n.inputs:n.inputs['Roughness'].default_value=.38
 if n.type=='MIX_SHADER' and n.name=='Mix Shader.001':n.inputs[0].default_value=.18
for o,factor in zip(parts,[1,.91,1.07,.87,1.03,.95,.9]):o.scale.x*=factor
bpy.ops.wm.save_as_mainfile(filepath=str(out));(base/'refinement02.json').write_text(json.dumps({'source':'plant.blend','candidate':str(out),'changes':['Native leaf pigmentation gain RGB(.28,.42,.24),not exposure','Native wax-gloss roughness.38 andtranslucent mix.18','Petiole radius up to3x below60percent leaf height,taper tooriginal atblade','Small per-leaf width variation;same7native components'],'maximum_vertex_change_normalized_m':float(np.linalg.norm(coords-before,axis=1).max()),'lighting_camera_exposure':'unchanged','photorealism_accepted':False,'requires':'Same studio render;no swollen stems,artifacts orblack leaves;placement/root support still unverified'},indent=2));print('SAVED',out,flush=True)
