"""Measured front-leg UV correction:source48 already had lengthwise axes;49 over-swapped them."""
import bpy,json,hashlib,math
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];base=ROOT/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full';ref=ROOT/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';src=base/'scene_candidate_r49.blend';out=base/'scene_candidate_r50.blend';assert not out.exists();sha=hashlib.sha256(src.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(src));rows=[]
for o in bpy.data.objects:
 key=o.get('program_key','')
 if o.type!='MESH' or not key.startswith('breakout_chair') or o.parent is not None:continue
 o.data=o.data.copy();uv=o.data.uv_layers.active;count=0;before=[];after=[]
 for f in o.data.polygons:
  if o.data.materials[f.material_index].name!='R49_lengthwise_scan_oak':continue
  for li in f.loop_indices:
   q=o.data.vertices[o.data.loops[li].vertex_index].co;assert q.x>0;cx=.2;cy=.2 if q.y>0 else -.2;before.append(list(uv.data[li].uv));uv.data[li].uv=(q.z,math.atan2(q.y-cy,q.x-cx)/math.tau*.1);assert abs(uv.data[li].uv.x-q.z)<1e-6;after.append(list(uv.data[li].uv));count+=1
 o.data.update();rows.append({'object':o.name,'corrected_side_loops':count,'sample_before':before[:4],'sample_after':after[:4],'mapping':'U=leg height m,V=circumferential angular coordinate*0.1;cut-end UV untouched'})
assert len(rows)==4;bpy.ops.wm.save_as_mainfile(filepath=str(out));assert hashlib.sha256(src.read_bytes()).hexdigest()==sha;(ref/'realism_refinement_r50.json').write_text(json.dumps({'source':str(src),'source_sha256':sha,'candidate':str(out),'scope':'front leg side UV only;all geometry,materials,cap UV,rear stiles,lighting unchanged','root_cause':'Measured source48 front UV already used U=height;blind49 swap was wrong for these objects. Rear members needed different orientation.','changes':rows,'photorealism_accepted':False,'requires':'same front/rear actual images,check horizontal bands andscale;normal diagnostic49 remains separate'},indent=2));print('SAVED',out,flush=True)
