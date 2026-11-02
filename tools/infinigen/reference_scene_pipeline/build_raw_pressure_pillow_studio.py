"""Fast isolated old/new geometry A/B before expensive room renders;neutral material,no seam curves."""
import bpy,json,hashlib,sys
from pathlib import Path
from mathutils import Vector
from mathutils import Matrix
import numpy as np
def make_shape(native,width,height,depth,angle,roll,**kw):
 a=np.asarray([list(v.co) for v in native.vertices]);c=(a.max(0)+a.min(0))/2;h=(a.max(0)-a.min(0))/2;m=native.copy();R=Matrix.Rotation(angle,4,"Y")@Matrix.Rotation(roll,4,"X")
 for v in m.vertices:
  q=(np.asarray(v.co)-c)/h;v.co=R@Vector((q[2]*depth,q[0]*width/2,q[1]*height/2))
 m.update();return m,0
ROOT=Path(__file__).resolve().parents[3];ref=ROOT/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';root=ref/'native_pressure_pillow_studio';assert not root.exists();root.mkdir();bpy.ops.wm.read_factory_settings(use_empty=True)
with bpy.data.libraries.load(str(ref/'native_pillow_prototypes.blend'),link=False) as (a,b):b.objects=['NativePressurePillow_1']
proto=b.objects[0];bpy.context.scene.collection.objects.link(proto);bpy.context.view_layer.update();native=bpy.data.meshes.new_from_object(proto.evaluated_get(bpy.context.evaluated_depsgraph_get()));bpy.data.objects.remove(proto,do_unlink=True);scene=bpy.context.scene;world=bpy.data.worlds.new('Studio_world');world.use_nodes=True;world.node_tree.nodes.get('Background').inputs['Strength'].default_value=.12;scene.world=world
m=bpy.data.materials.new('Studio_neutral_geometry');m.use_nodes=True;bs=m.node_tree.nodes.get('Principled BSDF');bs.inputs['Base Color'].default_value=(.32,.32,.32,1);bs.inputs['Roughness'].default_value=.42
bpy.ops.mesh.primitive_plane_add(size=200);ground=bpy.context.object;gm=bpy.data.materials.new('Studio_ground');gm.diffuse_color=(.16,.16,.16,1);ground.data.materials.append(gm)
for name,loc,power,size in [('key',(1.8,-1.5,2),230,.5),('fill',(.5,2,1.6),70,1.5)]:
 data=bpy.data.lights.new(name,'AREA');data.energy=power;data.shape='DISK';data.size=size;o=bpy.data.objects.new(name,data);scene.collection.objects.link(o);o.location=loc;o.rotation_euler=(Vector((0,0,.22))-o.location).to_track_quat('-Z','Y').to_euler()
views=[{'name':'pillow_geometry_studio','location':[1.1,-.75,.55],'target':[0,0,.22],'hfov':50,'render_width':960,'samples':32}];(root/'views.json').write_text(json.dumps(views,indent=2));rows=[]
for mode in ['raw_pressure']:
 mesh,compression=make_shape(native,.62,.42,.113,-.24,-.035,corner_mode=mode);mesh.materials.clear();mesh.materials.append(m);o=bpy.data.objects.new('Isolated_pillow',mesh);scene.collection.objects.link(o);o.location.z=-min(v.co.z for v in mesh.vertices);out=root/(mode+'.blend');bpy.ops.wm.save_as_mainfile(filepath=str(out));rows.append({'mode':mode,'blend':str(out),'sha256':hashlib.sha256(out.read_bytes()).hexdigest(),'maximum_lower_compression_m':compression,'scope':'geometry only;no fabric shader orpiping;old/newsame camera,materials,light'});bpy.data.objects.remove(o,do_unlink=True)
(root/'provenance.json').write_text(json.dumps({'kernel_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'artifacts':rows,'photorealism_accepted':False,'goal':'Inspect unmodified native pressure contour before imposing planar rest-outline corrections'},indent=2));print(json.dumps(rows),flush=True)
