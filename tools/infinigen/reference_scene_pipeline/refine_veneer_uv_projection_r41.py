"""Correct UV-fed BOX image sampling: explicit surface UV requires FLAT projection."""
import bpy,json,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];base=ROOT/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full';ref=ROOT/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';src=base/'scene_candidate_r40.blend';out=base/'scene_candidate_r41.blend';assert not out.exists();sha=hashlib.sha256(src.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(src));rows=[];done=set()
for o in bpy.data.objects:
 if o.type!='MESH' or o.get('program_key') not in ['coffee_cabinet_front','coffee_upper_front']:continue
 for slot in o.material_slots:
  m=slot.material
  if not m or m.name in done:continue
  m=m.copy();m.name='BreakoutR41_UV_oak_veneer';slot.material=m;done.add(m.name)
  for n in m.node_tree.nodes:
   if n.type=='TEX_IMAGE':
    old=n.projection;n.projection='FLAT';rows.append({'object':o.name,'material':m.name,'image':n.image.name if n.image else None,'old_projection':old,'new_projection':'FLAT'})
assert rows
bpy.ops.wm.save_as_mainfile(filepath=str(out));assert hashlib.sha256(src.read_bytes()).hexdigest()==sha;(ref/'realism_refinement_r41.json').write_text(json.dumps({'source':str(src),'candidate':str(out),'source_sha256':sha,'trigger':'Independent r38 cabinet vertical banding. Source33 explicitly maps wood UV but scan helper sets BOX projection, so physical normal chooses incompatible projected coordinate axes.','scope':'cabinet front image projection only;UV coordinates,scan files,material response,geometry,light and exposure unchanged','changes':rows,'photorealism_accepted':False,'requires':'same-camera veneer grain detail comparison'},indent=2));print('SAVED',out,flush=True)
