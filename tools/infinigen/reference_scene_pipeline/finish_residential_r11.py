"""Match reference charcoal frames and add physically folded bedroom curtains."""
import bpy,math,json
from pathlib import Path
from mathutils import Vector
ROOT=Path(__file__).resolve().parents[3];base=ROOT/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full';ref=ROOT/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03'
bpy.ops.wm.open_mainfile(filepath=str(base/'scene_candidate_r10.blend'))
dark=bpy.data.materials['res03_charcoal'];fabric=bpy.data.materials['res03_sheer_linen'];count=0
for o in bpy.data.objects:
 if o.type=='MESH' and 'WindowFactory' in o.name:
  for slot in o.material_slots:
   if slot.material and slot.material.name.startswith(('shader_wood','shader_shelves_black_wood')):slot.material=dark;count+=1
floor=bpy.data.objects['bedroom_0/0.floor'];fz=max((floor.matrix_world@Vector(c)).z for c in floor.bound_box)
cz=min(min((o.matrix_world@Vector(c)).z for c in o.bound_box) for o in bpy.data.objects if o.name.endswith('.ceiling'))
for unit in (101,102):
 for room,y,edges in [('master',17.85,[5.62,8.38]),('bedroom3',.15,[.62,4.28])]:
  for edge in edges:
   verts=[];faces=[];n=40
   for z in (fz+.045,cz-.15):
    for i in range(n+1):
     x=edge-.17+.34*i/n;xx=21.5-x if unit==102 else x
     verts.append((xx,y+.025*math.sin(i*math.pi/3),z))
   for i in range(n):faces.append((i,i+1,n+2+i,n+1+i))
   me=bpy.data.meshes.new('folded_bedroom_sheer');me.from_pydata(verts,[],faces);me.materials.append(fabric);o=bpy.data.objects.new(f'Residential03_r11_{unit}_{room}_curtain',me);bpy.context.scene.collection.objects.link(o)
   o['reference_scene_owner']='dual_unit_residential_floor_03';o['program_key']=f'{unit}_{room}_curtain';o['audit_kind']='fixture'
out=base/'scene_candidate_r11.blend';assert not out.exists();bpy.ops.wm.save_as_mainfile(filepath=str(out))
(ref/'finishing_r11.json').write_text(json.dumps({'source':'scene_candidate_r10.blend','charcoal_window_slots':count,'folded_curtain_panels':8,'visual_acceptance':False},indent=2))
