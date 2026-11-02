"""Neutral two-angle preview of the baked one-shirt mass diagnostic; no room mutation."""
import bpy,json
from pathlib import Path
from mathutils import Vector
r=Path('/jarvis/project/robomituba/data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03')
out=r/'garment_mass_corrected_pilot01_studio';assert not out.exists();out.mkdir()
bpy.ops.wm.open_mainfile(filepath=str(r/'garment_mass_corrected_pilot01.blend'))
# Simulation bakes shirt into local hanger coordinates; collider geometry retained world origin z=2.
for o in bpy.data.objects:
 if o.name.startswith('Temporary_wire_'):o.location.z-=2
s=bpy.context.scene
w=bpy.data.worlds.new('Neutral diagnostic world');w.use_nodes=True;w.node_tree.nodes['Background'].inputs['Strength'].default_value=.2;s.world=w
for name,loc,power,size in [('Key',(1,-1.5,1),100,1),('Fill',(-1,1,.3),40,1)]:
 d=bpy.data.lights.new(name,'AREA');d.energy=power;d.size=size;o=bpy.data.objects.new(name,d);s.collection.objects.link(o);o.location=loc;o.rotation_euler=(Vector((0,0,-.25))-o.location).to_track_quat('-Z','Y').to_euler()
bpy.ops.wm.save_as_mainfile(filepath=str(out/'studio.blend'))
(out/'views.json').write_text(json.dumps([{'name':'shirt_front','location':[.1,-1.4,-.18],'target':[0,0,-.27],'hfov':35,'render_width':640,'samples':16},{'name':'shirt_oblique','location':[.9,-1,-.15],'target':[0,0,-.27],'hfov':35,'render_width':640,'samples':16}],indent=2))
print(out)
