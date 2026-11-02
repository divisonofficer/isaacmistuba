"""Native library book shape/material preview before office placement."""
import bpy,json,math
from pathlib import Path
from mathutils import Vector,Matrix
r=Path('/jarvis/project/robomituba');out=r/'data/venue_refs/floor_plans_v3/commercial_office_floor_02/native_books_studio02';assert not (out/"studio.blend").exists();out.mkdir(exist_ok=True);bpy.ops.wm.read_factory_settings(use_empty=True);records=[]
def refine_book(o,j):
 colors=[(.025,.045,.065),(.12,.17,.13),(.24,.19,.14)];titles=['FIELD NOTES','MATERIAL STUDIES','PROJECT ARCHIVE']
 m=bpy.data.materials.new('Office cloth-bound cover '+str(j));m.use_nodes=True;bs=m.node_tree.nodes['Principled BSDF'];bs.inputs['Base Color'].default_value=(*colors[j],1);bs.inputs['Roughness'].default_value=.62
 for i,old in enumerate(o.data.materials):
  if old and 'shader_text' in old.name:o.data.materials[i]=m
 be=o.modifiers.new('Manufactured book edge radius','BEVEL');be.width=.0003;be.segments=2
 bpy.context.view_layer.update();pts=[o.matrix_world@Vector(c) for c in o.bound_box];lo=Vector([min(q[k] for q in pts) for k in range(3)]);hi=Vector([max(q[k] for q in pts) for k in range(3)])
 ink=bpy.data.materials.get('Office book warm-white ink')
 if ink is None:
  ink=bpy.data.materials.new('Office book warm-white ink');ink.use_nodes=True;ink.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value=(.72,.69,.60,1);ink.node_tree.nodes['Principled BSDF'].inputs['Roughness'].default_value=.6
 for kind in ['spine','cover']:
  data=bpy.data.curves.new(titles[j]+' '+kind,'FONT');data.body=titles[j] if kind=='spine' else titles[j].replace(' ','\n',1)+'\n0'+str(j+1);data.align_x='CENTER';data.align_y='CENTER';data.size=.007 if kind=='spine' else .012;data.extrude=.00003
  text=bpy.data.objects.new(data.name,data);bpy.context.scene.collection.objects.link(text);data.materials.append(ink)
  if kind=='spine':text.location=(lo.x-.0002,(lo.y+hi.y)/2,(lo.z+hi.z)/2);text.rotation_euler=Matrix(((0,0,-1),(0,1,0),(1,0,0))).to_euler()
  else:text.location=((lo.x+hi.x)/2,lo.y-.0002,lo.z+(hi.z-lo.z)*.70);text.rotation_euler.x=math.pi/2

for j,seed in enumerate([1,4,8]):
 p=r/f'data/object_library_v2/books/book_{seed:03}.blend'
 with bpy.data.libraries.load(str(p),link=False) as (a,b):b.objects=['ir_obj']
 o=b.objects[0];bpy.context.scene.collection.objects.link(o);o.name=f'Native_book_{seed:03}';o.rotation_euler.x=math.pi/2;bpy.context.view_layer.update();pts=[o.matrix_world@Vector(c) for c in o.bound_box];lo=Vector([min(q[k] for q in pts) for k in range(3)]);hi=Vector([max(q[k] for q in pts) for k in range(3)]);o.location-=Vector(((lo.x+hi.x)/2,(lo.y+hi.y)/2,lo.z));o.location.y+=(j-1)*.095;refine_book(o,j);records.append({'asset':str(p),'object':o.name,'dimensions':list(hi-lo),'materials':[m.name for m in o.data.materials]})
bpy.ops.mesh.primitive_plane_add(size=200);o=bpy.context.object;m=bpy.data.materials.new('Studio desk');m.use_nodes=True;m.node_tree.nodes['Principled BSDF'].inputs['Base Color'].default_value=(.25,.25,.25,1);o.data.materials.append(m)
w=bpy.data.worlds.new('Studio');w.use_nodes=True;w.node_tree.nodes['Background'].inputs['Strength'].default_value=.25;bpy.context.scene.world=w
for name,loc,power,size in [('Key',(-1,-1,1.5),80,1),('Fill',(1,1,1),35,1)]:
 d=bpy.data.lights.new(name,'AREA');d.energy=power;d.size=size;o=bpy.data.objects.new(name,d);bpy.context.scene.collection.objects.link(o);o.location=loc;o.rotation_euler=(Vector((0,0,.15))-o.location).to_track_quat('-Z','Y').to_euler()
bpy.ops.wm.save_as_mainfile(filepath=str(out/'studio.blend'));(out/'views.json').write_text(json.dumps([{'name':'native_books','location':[-.7,-.65,.48],'target':[0,0,.15],'hfov':40,'render_width':768,'samples':32}],indent=2));(out/'provenance.json').write_text(json.dumps({'source_assets':records,'acceptance':False,'scope':'no scene placement; library shape/material preview only'},indent=2));print(out,flush=True)
