"""Native library book shape/material preview before office placement."""
import bpy,json,math
from pathlib import Path
from mathutils import Vector
r=Path('/jarvis/project/robomituba');out=r/'data/venue_refs/floor_plans_v3/commercial_office_floor_02/native_books_studio01';assert not (out/"studio.blend").exists();out.mkdir(exist_ok=True);bpy.ops.wm.read_factory_settings(use_empty=True);records=[]
for j,seed in enumerate([1,4,8]):
 p=r/f'data/object_library_v2/books/book_{seed:03}.blend'
 with bpy.data.libraries.load(str(p),link=False) as (a,b):b.objects=['ir_obj']
 o=b.objects[0];bpy.context.scene.collection.objects.link(o);o.name=f'Native_book_{seed:03}';o.rotation_euler.x=math.pi/2;bpy.context.view_layer.update();pts=[o.matrix_world@Vector(c) for c in o.bound_box];lo=Vector([min(q[k] for q in pts) for k in range(3)]);hi=Vector([max(q[k] for q in pts) for k in range(3)]);o.location-=Vector(((lo.x+hi.x)/2,(lo.y+hi.y)/2,lo.z));o.location.y+=(j-1)*.095;records.append({'asset':str(p),'object':o.name,'dimensions':list(hi-lo),'materials':[m.name for m in o.data.materials]})
bpy.ops.mesh.primitive_plane_add(size=200);o=bpy.context.object;m=bpy.data.materials.new('Studio desk');m.use_nodes=True;m.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value=(.25,.25,.25,1);o.data.materials.append(m)
w=bpy.data.worlds.new('Studio');w.use_nodes=True;w.node_tree.nodes['Background'].inputs['Strength'].default_value=.25;bpy.context.scene.world=w
for name,loc,power,size in [('Key',(-1,-1,1.5),80,1),('Fill',(1,1,1),35,1)]:
 d=bpy.data.lights.new(name,'AREA');d.energy=power;d.size=size;o=bpy.data.objects.new(name,d);bpy.context.scene.collection.objects.link(o);o.location=loc;o.rotation_euler=(Vector((0,0,.15))-o.location).to_track_quat('-Z','Y').to_euler()
bpy.ops.wm.save_as_mainfile(filepath=str(out/'studio.blend'));(out/'views.json').write_text(json.dumps([{'name':'native_books','location':[-.7,-.65,.48],'target':[0,0,.15],'hfov':40,'render_width':768,'samples':32}],indent=2));(out/'provenance.json').write_text(json.dumps({'source_assets':records,'acceptance':False,'scope':'no scene placement; library shape/material preview only'},indent=2));print(out,flush=True)
