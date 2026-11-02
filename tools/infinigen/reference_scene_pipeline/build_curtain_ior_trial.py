"""Second isolated optical correction; preserves failed metallic-only B diagnostic."""
import bpy,json,hashlib
from pathlib import Path
r=Path(__file__).resolve().parents[3];d=r/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';src=d/'curtain_dielectric_trial/candidate.blend';out=d/'curtain_ior_trial';out.mkdir(exist_ok=True);dst=out/'candidate.blend';assert not dst.exists();sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();before=sha(src);bpy.ops.wm.open_mainfile(filepath=str(src));changes=[]
for o in bpy.data.objects:
 if o.type!='MESH' or o.get('original_asset_id')!='HSSD_3ba480f5ac90ffd829b38acb17e344602f952c06':continue
 for m in o.data.materials:
  bs=next(n for n in m.node_tree.nodes if n.type=='BSDF_PRINCIPLED');s=bs.inputs['IOR'];assert not s.is_linked and s.default_value==0.;s.default_value=1.46;changes.append({'material':m.name,'ior_before':0.,'ior_after':1.46,'metallic':float(bs.inputs['Metallic'].default_value),'roughness':float(bs.inputs['Roughness'].default_value),'inferred_not_measured':True})
assert changes;bpy.ops.wm.save_as_mainfile(filepath=str(dst));(out/'views.json').write_text((d/'curtain_dielectric_trial/views.json').read_text());assert sha(src)==before;(out/'build.json').write_text(json.dumps({'source':str(src),'source_sha256':before,'candidate':str(dst),'candidate_sha256':sha(dst),'changes':changes,'accepted':False,'scope':'C repairs residual physically invalid IOR0 after B corrected metallic only. B preserved, not adopted. Native mesh, maps, roughness, studio lights and camera unchanged. No final textile realism claim.'},indent=2));print('CURTAIN_IOR_TRIAL_SAVED')
