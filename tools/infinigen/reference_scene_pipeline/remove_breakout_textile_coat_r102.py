"""One proved optical correction on the actual chair family; source101 preserved."""
import bpy,json,hashlib,sys
from pathlib import Path
R=Path(__file__).resolve().parents[3];sys.path.insert(0,str(Path(__file__).parent))
from shader_optical_signature import optical_signature
D=R/'data/venue_refs/floor_plans_v3/commercial_office_floor_02'
B=R/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full'
source=B/'scene_candidate_r101.blend';out=B/'scene_candidate_r102.blend';assert not out.exists()
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
meta=json.loads((D/'realism_refinement_r101.json').read_text());assert sha(source)==meta['candidate_sha256']
bpy.ops.wm.open_mainfile(filepath=str(source))
parts=[bpy.data.objects[name] for row in meta['breakout_chair_records'] for name in row['parts']]
targets={m for obj in parts for m in obj.data.materials if m and m.name.startswith('BreakoutAAC23_authored_blue_native_fabric')}
assert len(targets)==1
old=next(iter(targets));body_objects=[o.name for o in parts if old in list(o.data.materials)];assert len(body_objects)==4
signature=optical_signature(old,('Coat Weight',))
mat=old.copy();mat.name='R102_uncoated_blue_upholstery'
bs=next(n for n in mat.node_tree.nodes if n.type=='BSDF_PRINCIPLED')
assert not bs.inputs['Coat Weight'].is_linked
before=float(bs.inputs['Coat Weight'].default_value);assert before>.5
bs.inputs['Coat Weight'].default_value=0
assert optical_signature(mat,('Coat Weight',))==signature
for obj in parts:
    for i,material in enumerate(obj.data.materials):
        if material==old:obj.data.materials[i]=mat
assert all(mat in list(bpy.data.objects[name].data.materials) for name in body_objects)
bpy.ops.wm.save_as_mainfile(filepath=str(out));assert sha(source)==meta['candidate_sha256']
meta.update(source=str(source),source_sha256=sha(source),candidate=str(out),candidate_sha256=sha(out),
    change='Only selected AAC23 woven upholstery Coat Weight .574116 ->0 after actual albedo/normal/sheen/coat ablations. Keep all chair/native geometry,UV,placement,base colour,normal,roughness,sheen,legs,world/lights/cameras.',
    breakout_textile_optical_contract={'material':mat.name,'body_objects':body_objects,'coat_weight_before':before,
        'coat_weight_after':0,'shader_signature_except_coat_sha256':signature,
        'evidence':'real_breakout_chair_candidates/aac23_blue_wood_variant/surface_cause_probe/visual_review.json',
        'role':'explicit selected uncoated woven upholstery, not a global clearcoat-removal policy'},
    photorealism_accepted=False)
(D/'realism_refinement_r102.json').write_text(json.dumps(meta,indent=2))
print('BREAKOUT_TEXTILE_COAT102_SAVED',before,flush=True)
