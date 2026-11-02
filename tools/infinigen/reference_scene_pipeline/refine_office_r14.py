"""Full-view review batch: resolve fridge z-fighting and improve carpet weave contrast."""
import bpy,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];sys.path.insert(0,str(ROOT/'tools/infinigen'))
from carpet_floor import _bake
base=ROOT/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full';ref=ROOT/'data/venue_refs/floor_plans_v3/commercial_office_floor_02'
bpy.ops.wm.open_mainfile(filepath=str(base/'scene_candidate_r13.blend'))
from mathutils import Vector
floor=bpy.data.objects['kitchen_0/0.floor'];fz=max((floor.matrix_world@Vector(c)).z for c in floor.bound_box)
fridge=next(o for o in bpy.data.objects if o.get('program_key')=='coffee_fridge')
fridge.dimensions.z=.77;fridge.location.z=fz+.4725
# Original .12 streak contrast was a deliberately plain carpet. The reference
# instead has visibly directional mottled carpet tiles; preserve physical scale.
path,period=_bake((.30,.31,.32),.5,.075,.45);image=bpy.data.images.load(str(path),check_existing=True);image.colorspace_settings.name='sRGB'
mat=bpy.data.materials['ReferencePBR_loop_pile_carpet'];changed=0
for node in mat.node_tree.nodes:
 if node.type=='TEX_IMAGE' and node.image and node.image.name.startswith('cp_'):node.image=image;changed+=1
assert changed==1
charcoal=bpy.data.materials['office02_charcoal'];frames=0
for o in bpy.data.objects:
 if o.type=='MESH' and 'WindowFactory' in o.name:
  for slot in o.material_slots:
   if slot.material and slot.material.name.startswith(('shader_wood','shader_shelves_black_wood')):slot.material=charcoal;frames+=1
out=base/'scene_candidate_r14.blend';assert not out.exists();bpy.ops.wm.save_as_mainfile(filepath=str(out))
(ref/'material_detail_r14.json').write_text(json.dumps({'source':'scene_candidate_r13.blend','carpet':'0.5m directional mottled tiles, .45 strand contrast, scan roughness/normal retained','fridge':'Top lowered below worktop to remove coplanar overlap/z-fighting','charcoal_window_slots':frames,'visual_acceptance':False},indent=2))
