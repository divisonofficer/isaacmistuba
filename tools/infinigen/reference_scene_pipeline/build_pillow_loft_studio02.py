"""Fast isolated old/new geometry A/B before expensive room renders;neutral material,no seam curves."""
import bpy,json,hashlib,sys
from pathlib import Path
from mathutils import Vector
from pillow_loft_experiment import make_shape
ROOT=Path(__file__).resolve().parents[3];ref=ROOT/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';root=ref/'pillow_loft_studio02';assert not root.exists();root.mkdir();bpy.ops.wm.read_factory_settings(use_empty=True)
with bpy.data.libraries.load(str(ref/'native_pillow_panel_rest90_prototypes.blend'),link=False) as (a,b):b.objects=['NativePanelRestPillow_1']
proto=b.objects[0];bpy.context.scene.collection.objects.link(proto);bpy.context.view_layer.update();native=bpy.data.meshes.new_from_object(proto.evaluated_get(bpy.context.evaluated_depsgraph_get()));bpy.data.objects.remove(proto,do_unlink=True);scene=bpy.context.scene;world=bpy.data.worlds.new('Studio_world');world.use_nodes=True;world.node_tree.nodes.get('Background').inputs['Strength'].default_value=.12;scene.world=world
m=bpy.data.materials.new('Studio_neutral_geometry');m.use_nodes=True;bs=m.node_tree.nodes.get('Principled BSDF');bs.inputs['Base Color'].default_value=(.32,.32,.32,1);bs.inputs['Roughness'].default_value=.42
bpy.ops.mesh.primitive_plane_add(size=200);ground=bpy.context.object;gm=bpy.data.materials.new('Studio_ground');gm.diffuse_color=(.16,.16,.16,1);ground.data.materials.append(gm)
for name,loc,power,size in [('key',(1.8,-1.5,2),230,.5),('fill',(.5,2,1.6),70,1.5)]:
 data=bpy.data.lights.new(name,'AREA');data.energy=power;data.shape='DISK';data.size=size;o=bpy.data.objects.new(name,data);scene.collection.objects.link(o);o.location=loc;o.rotation_euler=(Vector((0,0,.22))-o.location).to_track_quat('-Z','Y').to_euler()
views=[{'name':'pillow_geometry_studio','location':[1.1,-.75,.55],'target':[0,0,.22],'hfov':50,'render_width':960,'samples':32}];(root/'views.json').write_text(json.dumps(views,indent=2));rows=[]
for mode in ['native','filled']:
 mesh,compression=make_shape(native,.62,.42,(.105 if mode=="filled" else .065),-.24,-.035,corner_mode="local_smooth",loft_mode=mode);mesh.materials.clear();mesh.materials.append(m);o=bpy.data.objects.new('Isolated_pillow',mesh);scene.collection.objects.link(o);o.location.z=-min(v.co.z for v in mesh.vertices);out=root/(mode+'.blend');bpy.ops.wm.save_as_mainfile(filepath=str(out));rows.append({'mode':mode,'blend':str(out),'sha256':hashlib.sha256(out.read_bytes()).hexdigest(),'maximum_lower_compression_m':compression,'scope':'geometry only;no fabric shader orpiping;old/newsame camera,materials,light'});bpy.data.objects.remove(o,do_unlink=True)
(root/'provenance.json').write_text(json.dumps({'kernel_sha256':hashlib.sha256(Path(__file__).with_name('pillow_loft_experiment.py').read_bytes()).hexdigest(),'artifacts':rows,'photorealism_accepted':False,'goal':'Compare native face amplitude with absolute filling envelope; isolated geometry trial, no scene acceptance'},indent=2));print(json.dumps(rows),flush=True)
