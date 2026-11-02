import bpy,json,math,argparse
from pathlib import Path
from mathutils import Vector
p=argparse.ArgumentParser();p.add_argument('--asset',default='bush_001');p.add_argument('--tag',default='bush');p.add_argument('--height',type=float,default=1.35);a=p.parse_args();target_height=a.height;assert .1<target_height<3
assert '/' not in a.asset and '/' not in a.tag
r=Path('/jarvis/project/robomituba');out=r/f'data/venue_refs/floor_plans_v3/commercial_office_floor_02/plant_library_{a.tag}_studio';assert not out.exists();out.mkdir();bpy.ops.wm.read_factory_settings(use_empty=True)
with bpy.data.libraries.load(str(r/f'data/plant_library_v2/{a.asset}.blend'),link=False) as (a,b):b.objects=['ir_plant']
o=b.objects[0];bpy.context.scene.collection.objects.link(o);bpy.context.view_layer.update();pts=[o.matrix_world@Vector(c) for c in o.bound_box];lo=Vector([min(q[i] for q in pts) for i in range(3)]);hi=Vector([max(q[i] for q in pts) for i in range(3)]);scale=target_height/(hi.z-lo.z);o.scale*=scale;bpy.context.view_layer.update();pts=[o.matrix_world@Vector(c) for c in o.bound_box];o.location-=Vector(((min(q.x for q in pts)+max(q.x for q in pts))/2,(min(q.y for q in pts)+max(q.y for q in pts))/2,min(q.z for q in pts)));o.location.z+=.4
bpy.ops.mesh.primitive_cone_add(vertices=64,radius1=.19,radius2=.24,depth=.4,location=(0,0,.2));pot=bpy.context.object;pot.name='Preview_pot_proxy';m=bpy.data.materials.new('Preview_ceramic');m.use_nodes=True;m.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value=(.32,.30,.26,1);m.node_tree.nodes['Principled BSDF'].inputs['Roughness'].default_value=.5;pot.data.materials.append(m);be=pot.modifiers.new('Rim_edge','BEVEL');be.width=.008;be.segments=3
bpy.ops.mesh.primitive_plane_add(size=200);g=bpy.context.object;gm=bpy.data.materials.new('Ground');gm.diffuse_color=(.18,.18,.18,1);g.data.materials.append(gm)
w=bpy.data.worlds.new('Studio');w.use_nodes=True;w.node_tree.nodes['Background'].inputs['Strength'].default_value=.18;bpy.context.scene.world=w
for name,loc,power,size in [('Key',(2,-2,3),300,2),('Fill',(-2,1,2),150,2)]:
 d=bpy.data.lights.new(name,'AREA');d.energy=power;d.size=size;l=bpy.data.objects.new(name,d);bpy.context.scene.collection.objects.link(l);l.location=loc;l.rotation_euler=(Vector((0,0,.8))-l.location).to_track_quat('-Z','Y').to_euler()
bpy.ops.wm.save_as_mainfile(filepath=str(out/'bush.blend'));(out/'views.json').write_text(json.dumps([{'name':'bush_library_preview','location':[2.7,-3.3,2.1],'target':[0,0,.9],'hfov':42,'render_width':640,'samples':24}],indent=2));print(out,flush=True)
