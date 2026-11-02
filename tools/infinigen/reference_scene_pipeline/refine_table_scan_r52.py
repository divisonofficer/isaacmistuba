"""Isolated tabletop scan response trial, without changing light or other oak."""
import bpy,json,hashlib,argparse
import numpy as np
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
base=ROOT/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full'
ref=ROOT/'data/venue_refs/floor_plans_v3/commercial_office_floor_02'
p=argparse.ArgumentParser();p.add_argument('--revision',type=int,default=53);a=p.parse_args()
src=base/'scene_candidate_r51.blend';out=base/f'scene_candidate_r{a.revision}.blend'
assert not out.exists()
sha=hashlib.sha256(src.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(src))
table=next(o for o in bpy.data.objects if o.get('program_key')=='breakout_table')
slot=next(s for s in table.material_slots if s.material and s.material.name=='office02_reference_warm_oak')
m=slot.material.copy();m.name=f'R{a.revision}_table_scan_oak';slot.material=m
n=m.node_tree.nodes;l=m.node_tree.links
bs=next(x for x in n if x.type=='BSDF_PRINCIPLED')
tx=next(x for x in n if x.type=='TEX_IMAGE' and x.image and 'base_color' in x.image.filepath)
rough=next(x for x in n if x.type=='TEX_IMAGE' and x.image and 'roughness' in x.image.filepath)
pixels=np.empty(len(tx.image.pixels),dtype=np.float32);tx.image.pixels.foreach_get(pixels)
mean=tuple(float(x) for x in pixels.reshape(-1,tx.image.channels)[:,:3].mean(axis=0));target=(.34,.21,.11)
assert min(mean)>0
gain=n.new('ShaderNodeVectorMath');gain.operation='MULTIPLY'
gain.inputs[1].default_value=tuple(t/s for t,s in zip(target,mean))
l.new(tx.outputs['Color'],gain.inputs[0]);l.new(gain.outputs[0],bs.inputs['Base Color'])
rr=n.new('ShaderNodeMapRange');rr.inputs['To Min'].default_value=.25;rr.inputs['To Max'].default_value=.42
l.new(rough.outputs['Color'],rr.inputs['Value']);l.new(rr.outputs['Result'],bs.inputs['Roughness'])
for link in list(bs.inputs['Coat Roughness'].links):l.remove(link)
bs.inputs['Coat Weight'].default_value=.18;bs.inputs['Coat Roughness'].default_value=.20
bpy.ops.wm.save_as_mainfile(filepath=str(out));assert hashlib.sha256(src.read_bytes()).hexdigest()==sha
(ref/f'realism_refinement_r{a.revision}.json').write_text(json.dumps({'source':str(src),'source_sha256':sha,'candidate':str(out),'scope':'Only breakout tabletop oak material; existing scan coordinates and normals preserved; all geometry, lights and other materials unchanged','scan':tx.image.filepath,'scan_projection':tx.projection,'source_linear_mean':mean,'mean_measurement':'Actual Blender image linear pixels, all RGB samples','target_linear_mean':target,'roughness_range':[.25,.42],'photorealism_accepted':False,'requires':'Same wide frame comparison against51; reject oversized grain, unnatural colour or glossy plastic response'},indent=2))
print('SAVED',out,flush=True)
