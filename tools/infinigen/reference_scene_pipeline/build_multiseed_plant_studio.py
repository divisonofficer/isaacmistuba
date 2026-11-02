"""Use six actual native leaf variants,larger planter anddielectric leaf response."""
import bpy,json,numpy as np,math
from pathlib import Path
from mathutils import Vector,Euler
ROOT=Path(__file__).resolve().parents[3];ref=ROOT/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';out=ref/'multiseed_plant_studio';assert not out.exists();out.mkdir()
bpy.ops.wm.open_mainfile(filepath=str(ref/'assembled_leaf_plant_studio/plant.blend'))
for o in list(bpy.data.objects):
 if o.name.startswith('Indoor_leaf_'):bpy.data.objects.remove(o,do_unlink=True)
pot=bpy.data.objects['Hollow_planter'];pot.scale=(1.3,1.3,1.25)
soil=bpy.data.objects['Planter_soil'];soil.location.z=0
for v in soil.data.vertices:
 bottom=v.co.z<0;r=math.hypot(v.co.x,v.co.y);radius=.195 if bottom else .275
 if r>1e-9:v.co.x*=radius/r;v.co.y*=radius/r
 v.co.z=.03325 if bottom else .455
soil.data.update();parts=[];rows=[]
def leaf_material(old,index):
 m=old.copy();m.name=f'Indoor_scan_leaf_dielectric_{index}';n=m.node_tree.nodes;l=m.node_tree.links
 group=next(x for x in n if x.type=='GROUP' and 'Color' in x.inputs and x.inputs['Color'].is_linked);colour=group.inputs['Color'].links[0].from_socket
 bw=n.new('ShaderNodeRGBToBW');l.new(colour,bw.inputs[0]);rng=n.new('ShaderNodeMapRange');rng.inputs['To Min'].default_value=.91;rng.inputs['To Max'].default_value=1.09;l.new(bw.outputs[0],rng.inputs['Value'])
 mul=n.new('ShaderNodeVectorMath');mul.operation='MULTIPLY';mul.inputs[1].default_value=(.025,.065,.011);l.new(rng.outputs[0],mul.inputs[0])
 bs=n.new('ShaderNodeBsdfPrincipled');l.new(mul.outputs[0],bs.inputs['Base Color']);bs.inputs['IOR'].default_value=1.45;bs.inputs['Roughness'].default_value=.38;bs.inputs['Coat Weight'].default_value=.10;bs.inputs['Coat Roughness'].default_value=.25;bs.inputs['Subsurface Weight'].default_value=.04;bs.inputs['Subsurface Scale'].default_value=.001
 trans=n.new('ShaderNodeBsdfTranslucent');l.new(mul.outputs[0],trans.inputs['Color']);mix=n.new('ShaderNodeMixShader');mix.inputs[0].default_value=.10;l.new(bs.outputs[0],mix.inputs[1]);l.new(trans.outputs[0],mix.inputs[2]);output=next(x for x in n if x.type=='OUTPUT_MATERIAL');l.new(mix.outputs[0],output.inputs['Surface']);return m
config=[(1,1.35,18,0),(2,1.25,28,61),(3,1.50,10,126),(4,1.15,35,194),(5,1.40,22,257),(6,1.30,30,319),(1,.80,32,25),(3,.65,38,175)]
for i,(seed,height,tilt,yaw) in enumerate(config):
 asset=ROOT/f'data/plant_library_v2/plantbananatree_{seed:03}.blend'
 with bpy.data.libraries.load(str(asset),link=False) as(a,b):b.objects=['ir_plant']
 proto=b.objects[0];bpy.context.scene.collection.objects.link(proto);bpy.context.view_layer.update();mesh=bpy.data.meshes.new_from_object(proto.evaluated_get(bpy.context.evaluated_depsgraph_get()))
 a=np.empty(len(mesh.vertices)*3,dtype=np.float32);mesh.vertices.foreach_get('co',a);a=a.reshape(-1,3);M=np.asarray(proto.matrix_world);a=a@M[:3,:3].T+M[:3,3];root=np.median(a[a[:,2]<a[:,2].min()+.01],axis=0);a=(a-root)/(a[:,2].max()-a[:,2].min())
 z=a[:,2];bins=np.floor(z*160).astype(int)
 for band in np.unique(bins[z<.6]):
  idx=np.flatnonzero((bins==band)&(z<.6));center=np.median(a[idx,:2],axis=0);t=np.clip((.6-z[idx])/.15,0,1);a[idx,:2]=center+(a[idx,:2]-center)*(1+1.5*t*t*(3-2*t))[:,None]
 mesh.vertices.foreach_set('co',a.astype(np.float32).ravel());mesh.polygons.foreach_set('use_smooth',np.ones(len(mesh.polygons),dtype=bool));mesh.update()
 mats=[leaf_material(m,i) for m in mesh.materials];mesh.materials.clear()
 for m in mats:mesh.materials.append(m)
 bpy.data.objects.remove(proto,do_unlink=True);o=bpy.data.objects.new(f'Multiseed_leaf_{i}',mesh);bpy.context.scene.collection.objects.link(o);o.location=(.08*math.cos(i*2.4),.08*math.sin(i*2.4),.43);o.scale=(height,height,height);o.rotation_euler=Euler((math.radians(tilt),0,math.radians(yaw)),'XYZ');parts.append(o);rows.append({'object':o.name,'native_component':str(asset),'height_scale_m':height})
bpy.context.view_layer.update();bounds=[o.matrix_world@Vector(c) for o in parts for c in o.bound_box];bpy.ops.wm.save_as_mainfile(filepath=str(out/'plant.blend'));(out/'views.json').write_text((ref/'assembled_leaf_plant_studio/views.json').read_text());(out/'provenance.json').write_text(json.dumps({'parts':rows,'native_seed_variants':6,'leaf_count':8,'planter_width_m':.62,'planter_height_m':.4975,'leaf_bounds_m':[[min(v[i] for v in bounds) for i in range(3)],[max(v[i] for v in bounds) for i in range(3)]],'material':'Native pattern retained atrestrained9percent colour variation;dielectric IOR1.45,roughness.38,coat.10,translucent.10;actual native vein geometry retained','photorealism_accepted':False,'requires':'Actual image/independent inspection andsupport/room validation'},indent=2));print('SAVED',out,flush=True)
