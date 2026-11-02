"""Exact saved assigned-role material contract gate, not visual approval."""
import bpy,json,hashlib,sys,argparse
from pathlib import Path
parser=argparse.ArgumentParser();parser.add_argument('--revision',type=int,default=85);args=parser.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else []);rev=args.revision
R=Path(__file__).resolve().parents[3];D=R/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';S=R/f'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full/scene_candidate_r{rev}.blend';O=D/f'bed_material_contract_saved_audit_r{rev}.json';assert not O.exists();meta=json.loads((D/f'realism_refinement_r{rev}.json').read_text());bpy.ops.wm.open_mainfile(filepath=str(S));rows=[];errors=[]
for c in meta['changes']:
 m=bpy.data.materials[c['material']];objects=[o.name for o in bpy.context.scene.objects if o.type=='MESH' and any(x==m for x in o.data.materials)];bs=next(n for n in m.node_tree.nodes if n.type=='BSDF_PRINCIPLED');actual={k:bs.inputs[k].default_value for k in ['Metallic','Roughness','IOR']};ok=bool(objects) and all(not bs.inputs[k].is_linked and abs(actual[k]-c['after'][k])<1e-6 for k in actual)
 if not ok:errors.append({'material':m.name,'reason':'assigned_role_override_not_applied'})
 rows.append({'material':m.name,'objects':objects,'actual':actual,'expected':c['after'],'pass':ok})
h=hashlib.sha256(S.read_bytes()).hexdigest();assert h==meta['candidate_sha256'];O.write_text(json.dumps({'source':str(S),'source_sha256':h,'rows':rows,'errors':errors,'pass':not errors,'scope':'Five saved assigned bed materials match declared inferred role values,not measured BRDF or photo acceptance.','photorealism_accepted':False},indent=2)+'\n');print('BED_MATERIAL_SAVED_AUDIT',len(errors),flush=True);assert not errors,errors
