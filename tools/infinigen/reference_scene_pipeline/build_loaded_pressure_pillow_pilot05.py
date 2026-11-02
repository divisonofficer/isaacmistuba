"""Small real cloth/gravity contact trial; no room writes and no support acceptance by min-gap alone."""
import bpy,bmesh,sys,json,os
from pathlib import Path
from mathutils import Vector
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(Path(__file__).parent))
from pressure_contour_refinement import make_shape
ref=ROOT/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';out=ref/'loaded_pressure_pillow_pilot05';assert not out.exists();out.mkdir()
bpy.ops.wm.read_factory_settings(use_empty=True)
with bpy.data.libraries.load(str(ref/'native_pillow_panel_rest65_prototypes.blend'),link=False) as (a,b):b.objects=['NativePanelRestPillow_1']
proto=b.objects[0];native=proto.data.copy();mesh,_=make_shape(native,.62,.42,.113,-.24,-.035)
o=bpy.data.objects.new('Loaded_native_pillow',mesh);bpy.context.scene.collection.objects.link(o);bpy.data.objects.remove(proto,do_unlink=True)
bpy.context.view_layer.objects.active=o
dec=o.modifiers.new('Coarse_cloth_grid','DECIMATE');dec.decimate_type='UNSUBDIV';dec.iterations=4
bpy.ops.object.modifier_apply(modifier=dec.name);mesh=o.data
assert 1000<len(mesh.vertices)<5000,len(mesh.vertices)
o.location.z=-min(v.co.z for v in mesh.vertices)+.005
m=bpy.data.materials.new('Neutral_cloth');m.use_nodes=True;bs=m.node_tree.nodes.get('Principled BSDF');bs.inputs['Base Color'].default_value=(.32,.32,.32,1);bs.inputs['Roughness'].default_value=.42;mesh.materials.clear();mesh.materials.append(m)
def box(name,loc,dim):
 bpy.ops.mesh.primitive_cube_add(size=1,location=loc);q=bpy.context.object;q.name=name;q.dimensions=dim;bpy.ops.object.transform_apply(location=False,rotation=False,scale=True);q.modifiers.new('Contact','COLLISION');q.collision.thickness_outer=.001;return q
floor=box('Floor_contact',(0,0,-.05),(4,4,.1));backx=min(v.co.x for v in mesh.vertices)-.006;back=box('Back_contact',(backx-.04,0,.65),(.08,2,1.3))
scene=bpy.context.scene;scene.frame_start=1;scene.frame_end=50
cloth=o.modifiers.new('Gravity_and_pressure_contact','CLOTH');s=cloth.settings;s.quality=8;s.mass=1.2/len(mesh.vertices);s.tension_stiffness=15;s.compression_stiffness=15;s.shear_stiffness=5;s.bending_stiffness=.005;s.air_damping=3;s.use_pressure=True;s.uniform_pressure_force=0;s.effector_weights.gravity=1
bm=bmesh.new();bm.from_mesh(mesh);initial_volume=abs(bm.calc_volume());bm.free();assert initial_volume>0
s.use_pressure_volume=True;s.target_volume=initial_volume;s.pressure_factor=.3
c=cloth.collision_settings;c.use_collision=True;c.distance_min=.002;c.collision_quality=5;c.use_self_collision=True;c.self_distance_min=.003
cloth.point_cache.frame_start=1;cloth.point_cache.frame_end=50
state={'pid':os.getpid(),'phase':'simulating','frames':50,'coarse_vertices':len(mesh.vertices),'mass_per_vertex_kg':s.mass,'total_shell_mass_kg':s.mass*len(mesh.vertices),'target_volume_m3':initial_volume,'pressure_factor_kpa':s.pressure_factor,'physics':'Cloth gas volume target atinitial closed volume,0.3kPa pressure scale,1.2kg requested total mass,gravity/floor/back collisions;no pins/static compression','photorealism_accepted':False}
(out/'job.json').write_text(json.dumps(state,indent=2))
for frame in range(1,51):
 scene.frame_set(frame);bpy.context.view_layer.update()
 if frame%10==0:print('FRAME',frame,flush=True)
bpy.context.view_layer.objects.active=o;bpy.ops.object.modifier_apply(modifier=cloth.name)
sub=o.modifiers.new('Cloth_interpolation','SUBSURF');sub.levels=2;sub.render_levels=2
world=bpy.data.worlds.new('Studio');world.use_nodes=True;world.node_tree.nodes['Background'].inputs['Strength'].default_value=.12;scene.world=world
for name,loc,power,size in [('key',(1.8,-1.5,2),230,.5),('fill',(.5,2,1.6),70,1.5)]:
 d=bpy.data.lights.new(name,'AREA');d.energy=power;d.size=size;l=bpy.data.objects.new(name,d);scene.collection.objects.link(l);l.location=loc;l.rotation_euler=(Vector((0,0,.22))-l.location).to_track_quat('-Z','Y').to_euler()
bpy.ops.wm.save_as_mainfile(filepath=str(out/'pilot.blend'));(out/'views.json').write_text(json.dumps([{'name':'loaded_pillow','location':[1.1,-.75,.55],'target':[0,0,.22],'hfov':50,'render_width':960,'samples':32}],indent=2));state.update(phase='simulated_visual_review_pending');(out/'job.json').write_text(json.dumps(state,indent=2));print('SAVED',out,flush=True)
