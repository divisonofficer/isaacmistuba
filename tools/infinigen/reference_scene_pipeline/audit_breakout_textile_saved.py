"""Exact saved selected-textile optical contract; no global coating heuristic."""
import bpy,json,hashlib,sys,argparse
from pathlib import Path
R=Path(__file__).resolve().parents[3];sys.path.insert(0,str(Path(__file__).parent))
from shader_optical_signature import optical_signature
p=argparse.ArgumentParser();p.add_argument('--revision',required=True,type=int)
a=p.parse_args(sys.argv[sys.argv.index('--')+1:]);D=R/'data/venue_refs/floor_plans_v3/commercial_office_floor_02'
m=json.loads((D/f'realism_refinement_r{a.revision}.json').read_text());source=Path(m['candidate'])
sha=hashlib.sha256(source.read_bytes()).hexdigest();assert sha==m['candidate_sha256']
out=D/f'breakout_textile_saved_audit_r{a.revision}.json';assert not out.exists()
bpy.ops.wm.open_mainfile(filepath=str(source));c=m['breakout_textile_optical_contract'];mat=bpy.data.materials[c['material']]
bs=next(n for n in mat.node_tree.nodes if n.type=='BSDF_PRINCIPLED')
checks={'selected_four_body_objects_bound':len(c['body_objects'])==4 and all(mat in list(bpy.data.objects[name].data.materials) for name in c['body_objects']),
    'coat_weight_zero':not bs.inputs['Coat Weight'].is_linked and bs.inputs['Coat Weight'].default_value==0,
    'all_other_node_inputs_links_and_packed_images_preserved':optical_signature(mat,('Coat Weight',))==c['shader_signature_except_coat_sha256']}
errors=[k for k,v in checks.items() if not v]
out.write_text(json.dumps({'source':str(source),'source_sha256':sha,'checks':checks,'errors':errors,'pass':not errors,
    'photorealism_accepted':False,'scope':'Exact selected-material node/input/link/packed-image signature except Coat Weight, and four body bindings. Not geometric support,measured fabric response or RGB/reference acceptance.'},indent=2))
assert not errors,errors
print('BREAKOUT_TEXTILE_SAVED_AUDIT',flush=True)
