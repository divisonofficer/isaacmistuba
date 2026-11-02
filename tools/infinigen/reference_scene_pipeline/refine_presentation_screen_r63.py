"""Remove coarse normal relief from three display surfaces only; controlled r62 comparison."""
import bpy,json,hashlib
from pathlib import Path
r=Path('/jarvis/project/robomituba');base=r/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full';ref=r/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';src=base/'scene_candidate_r62.blend';dst=base/'scene_candidate_r63.blend';assert not dst.exists();sha=hashlib.sha256(src.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(src))
mat=bpy.data.materials['office02_presentation_screen'].copy();mat.name='R63_presentation_screen_without_coarse_relief';bs=next(n for n in mat.node_tree.nodes if n.type=='BSDF_PRINCIPLED');removed=[]
for link in list(bs.inputs['Normal'].links):
 removed.append((link.from_node.name,link.from_socket.name));mat.node_tree.links.remove(link)
assert removed
names=['Office02_conference_a_display','Office02_meeting_b_display','Office02_meeting_c_display']
for name in names:
 o=bpy.data.objects[name];assert len(o.data.materials)==1;o.data.materials[0]=mat
bpy.ops.wm.save_as_mainfile(filepath=str(dst));assert hashlib.sha256(src.read_bytes()).hexdigest()==sha
(ref/'realism_refinement_r63.json').write_text(json.dumps({'source':str(src),'source_sha256':sha,'candidate':str(dst),'objects':names,'change':'disconnect only coarse normal input from cloned display material; keep geometry/color/roughness/lighting/cameras unchanged','removed_normal_links':removed,'reason':'r62 blind/direct review: screen reflection reads as embossed rough panel; probe found Bump strength0.2 distance0.002m','photorealism_accepted':False},indent=2));print(dst,flush=True)
