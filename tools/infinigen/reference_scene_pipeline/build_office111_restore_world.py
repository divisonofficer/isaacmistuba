"""Restore captured urban world into actual109; audit historical world independently."""
import bpy,json,hashlib
from pathlib import Path
root=Path(__file__).resolve().parents[3];r=root/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';b=root/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full';src=b/'scene_candidate_r109_draft.blend';donor=b/'scene_candidate_r99.blend';dst=b/'scene_candidate_r111_draft.blend';assert not dst.exists();sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();before=sha(src);donor_sha=sha(donor);expected=json.loads((r/'world_environment_gate_r99.json').read_text())['expected_image_sha256'];bpy.ops.wm.open_mainfile(filepath=str(src));old=bpy.context.scene.world
with bpy.data.libraries.load(str(donor),link=False) as (a,z):z.worlds=list(a.worlds)
def reachable(world):
 outputs=[n for n in world.node_tree.nodes if n.type=='OUTPUT_WORLD' and n.is_active_output];assert len(outputs)==1;seen=set();todo=outputs[:]
 while todo:
  n=todo.pop()
  if n in seen:continue
  seen.add(n)
  for s in n.inputs:todo.extend(l.from_node for l in s.links)
 return seen
matches=[]
for w in z.worlds:
 if not w or not w.use_nodes:continue
 envs=[n for n in reachable(w) if n.type=='TEX_ENVIRONMENT' and n.image and n.image.packed_file]
 if any(hashlib.sha256(n.image.packed_file.data).hexdigest()==expected for n in envs):matches.append(w)
assert len(matches)==1,[(w.name) for w in matches];world=matches[0];world.name='Office111_actual_restored_urban_HDR';bpy.context.scene.world=world;active=list(reachable(world));assert any(n.type=='TEX_ENVIRONMENT' for n in active);assert not any(n.type=='LIGHT_PATH' for n in active)
bpy.ops.wm.save_as_mainfile(filepath=str(dst));assert sha(src)==before and sha(donor)==donor_sha
(r/'world111_build.json').write_text(json.dumps({'source':str(src),'source_sha256':before,'donor':str(donor),'donor_sha256':donor_sha,'candidate':str(dst),'candidate_sha256':sha(dst),'old_world':old.name,'new_world':world.name,'expected_packed_hdr_sha256':expected,'active_nodes':[{'name':n.name,'type':n.type} for n in active],'change':'Only scene world assignment to verified captured Canary Wharf HDR world. Geometry, furniture, source lights, exposure and cameras unchanged. World lighting changes for all ray types.','reason':'Actual109 re-opened world has active Nishita sky, so historical99 gate cannot establish current environment.','limits':'Donor appearance/yaw/illumination still needs current room A/B. No claim glazing geometry or photorealism solved.','accepted':False},indent=2));print('OFFICE111_ACTUAL_URBAN_WORLD_SAVED')
