"""Expose lift controls and complete complementary material/context views."""
import bpy,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];base=ROOT/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full';ref=ROOT/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03'
bpy.ops.wm.open_mainfile(filepath=str(base/'scene_candidate_r15.blend'))
for o in bpy.data.objects:
 if o.get('program_key')=='lift_call_panel':o.location.x=11.20
for m in bpy.data.materials:
 if m.name.startswith('ir_bal_teal'):
  bs=next(n for n in m.node_tree.nodes if n.type=='BSDF_PRINCIPLED')
  for link in list(bs.inputs['Base Color'].links):m.node_tree.links.remove(link)
  bs.inputs['Base Color'].default_value=(.23,.27,.235,1)
views=json.loads((base/'review_views_r14.json').read_text())
for unit in (101,102):
 mirror=lambda p:[21.5-p[0],p[1],p[2]] if unit==102 else p
 views.append({'name':f'{unit}_living_media_reverse','location':mirror([3.7,6.4,1.55]),'target':mirror([6.4,8.0,1.2]),'hfov':85})
 views.append({'name':f'{unit}_bedroom2_reverse','location':mirror([2.5,10.8,1.55]),'target':mirror([.7,10.75,.9]),'hfov':80})
(base/'review_views_r16.json').write_text(json.dumps(views,indent=2))
out=base/'scene_candidate_r16.blend';assert not out.exists();bpy.ops.wm.save_as_mainfile(filepath=str(out))
(ref/'correction_r16.json').write_text(json.dumps({'source':'scene_candidate_r15.blend','changes':['Lift call panel moved in front of wall surface','Balcony cloth colour unlinked from old colour graph and made muted sage','Living media/plant reverse and narrow-bedroom complementary cameras added'],'visual_acceptance':False},indent=2))
