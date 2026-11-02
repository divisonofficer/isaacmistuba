"""Current native sofa throw: original / smooth-only / smooth+affine depth comparison."""
import bpy,json,math,hashlib
import numpy as np
from pathlib import Path
from mathutils import Vector,Matrix
r=Path('/jarvis/project/robomituba');ref=r/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';source=r/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full/scene_candidate_r60.blend';out=ref/'sofa_throw_depth_studio01';assert not out.exists();out.mkdir();bpy.ops.wm.read_factory_settings(use_empty=True)
name='NativeR44_101_pressure_pillow_1'
with bpy.data.libraries.load(str(source),link=False) as (a,b):
 assert name in a.objects,(name,[x for x in a.objects if 'pressure_pillow' in x]);b.objects=[name]
original=b.objects[0];bpy.context.scene.collection.objects.link(original);original.parent=None;original.matrix_world=Matrix.Identity(4);native=original.data.copy();a=np.asarray([list(v.co) for v in native.vertices]);C=a.mean(0);eigenvalues,axes=np.linalg.eigh(np.cov((a-C).T));normal=axes[:,0];thickness=np.ptp((a-C)@normal);assert thickness>0;factor=.14/thickness;rows=[]
for j,kind in enumerate(['original','smooth_only','filled_depth']):
 o=original.copy();o.data=native.copy();bpy.context.scene.collection.objects.link(o);o.name=kind
 if kind!='original':o.data.polygons.foreach_set('use_smooth',np.ones(len(o.data.polygons),dtype=bool))
 if kind=='filled_depth':
  for v in o.data.vertices:
   q=np.asarray(v.co);v.co=Vector(q+normal*np.dot(q-C,normal)*(factor-1))
 o.data.update();co=np.asarray([list(v.co) for v in o.data.vertices]);o.location=(0,(j-1)*.8,-co[:,2].min());rows.append({'object':kind,'smooth_faces':sum(f.use_smooth for f in o.data.polygons),'faces':len(o.data.polygons),'normal_depth_m':float(np.ptp((co-C)@normal)),'world_axis_extents_m':np.ptp(co,axis=0).tolist()})
bpy.data.objects.remove(original,do_unlink=True)
bpy.ops.mesh.primitive_plane_add(size=200);o=bpy.context.object;m=bpy.data.materials.new('Diagnostic neutral floor');m.use_nodes=True;m.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value=(.20,.20,.20,1);o.data.materials.append(m)
w=bpy.data.worlds.new('Studio');w.use_nodes=True;w.node_tree.nodes['Background'].inputs['Strength'].default_value=.25;bpy.context.scene.world=w
for name,loc,power,size in [('Key',(1.5,-2,2.2),220,1.5),('Fill',(-1,2,1.5),80,1.5)]:
 d=bpy.data.lights.new(name,'AREA');d.energy=power;d.size=size;o=bpy.data.objects.new(name,d);bpy.context.scene.collection.objects.link(o);o.location=loc;o.rotation_euler=(Vector((0,0,.2))-o.location).to_track_quat('-Z','Y').to_euler()
bpy.ops.wm.save_as_mainfile(filepath=str(out/'studio.blend'));views=[]
for j,kind in enumerate(['original','smooth_only','filled_depth']):
 y=(j-1)*.8;views.append({'name':kind,'location':[.85,y-.65,.48],'target':[0,y,.21],'hfov':40,'render_width':768,'samples':32})
(out/'views.json').write_text(json.dumps(views,indent=2));(out/'provenance.json').write_text(json.dumps({'source':str(source),'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'source_object':'NativeR44_101_pressure_pillow_1','variants':rows,'depth_factor':float(factor),'change':'existing native pressure geometry; affine scaling along smallest PCA axis only in filled variant, plus actual smooth flags. Materials/UV retained. No new physics or room integration.','photorealism_accepted':False},indent=2));print(out,flush=True)
