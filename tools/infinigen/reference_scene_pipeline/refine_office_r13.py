"""Reduce overstrong brushed-metal striations found in direct r12 closeup."""
import bpy,json
from pathlib import Path
from material_detail import noise,bump,range_value
ROOT=Path(__file__).resolve().parents[3];base=ROOT/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full';ref=ROOT/'data/venue_refs/floor_plans_v3/commercial_office_floor_02'
bpy.ops.wm.open_mainfile(filepath=str(base/'scene_candidate_r12.blend'))
m=bpy.data.materials['ReferencePBR_brushed_stainless'];n=m.node_tree.nodes;l=m.node_tree.links;bs=next(x for x in n if x.type=='BSDF_PRINCIPLED');g=next(x for x in n if x.type=='NEW_GEOMETRY')
f=noise(n,l,g.outputs['Position'],40,(1,12,1));l.new(range_value(n,l,f,.22,.32),bs.inputs['Roughness']);l.new(bump(n,l,f,.000018,.25),bs.inputs['Normal']);bs.inputs['Anisotropic'].default_value=.45
out=base/'scene_candidate_r13.blend';assert not out.exists();bpy.ops.wm.save_as_mainfile(filepath=str(out))
(ref/'material_detail_r13.json').write_text(json.dumps({'source':'scene_candidate_r12.blend','reason':'r12 steel appears over-scratched; reduce roughness span and normal amplitude.','metallic':1,'roughness_range':[.22,.32],'nominal_bump_distance_m':.000018,'visual_acceptance':False},indent=2))
