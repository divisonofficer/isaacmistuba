"""Saved-source residential fine/role/texture preflight before targeted CPU RGB; no promotion."""
import argparse,json,os,subprocess
from pathlib import Path
from full_view_manifest import residential_canonical_path
ROOT=Path(__file__).resolve().parents[3];T=Path(__file__).parent;p=argparse.ArgumentParser();p.add_argument('--revision',type=int,required=True);p.add_argument('--names',required=True);p.add_argument('--tag',required=True);p.add_argument('--views',type=Path);a=p.parse_args();ref=ROOT/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';base=ROOT/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full';state=ref/f'checked_residential_round_r{a.revision}.json';assert not state.exists();d={'pid':os.getpid(),'revision':a.revision,'phase':'saved_preflight','photorealism_accepted':False};env={**os.environ,'CUDA_VISIBLE_DEVICES':''}
def save():state.write_text(json.dumps(d,indent=2));print(json.dumps(d),flush=True)
try:
 save();subprocess.run(['python3',str(T/'run_current_fine_audits.py'),'--scene','residential','--revision',str(a.revision)],cwd=ROOT,env=env,check=True)
 for stem in ['fine_features','required_spaces_audit','texture_dependencies','functional_assemblies','native_toiletry_assembly_audit','wc_layout_audit']:
  report=json.loads((ref/f'{stem}_r{a.revision}.json').read_text());assert not report.get('errors'),(stem,report.get('errors'))
 meta_path=ref/f'realism_refinement_r{a.revision}.json'
 meta=json.loads(meta_path.read_text()) if meta_path.exists() else {}
 if meta.get('unit102_lighting',{}).get('daylight_fill'):
  for unit in ['101','102']:
   subprocess.run(['python3',str(ROOT/'tools/infinigen/run_bundled_blender.py'),'-t','2','--background','--python-exit-code','1','--python',str(T/'audit_living_native_downlights_saved.py'),'--','--revision',str(a.revision),'--unit',unit],cwd=ROOT,env=env,check=True)
   name=f'living_downlights_saved_audit_r{a.revision}.json' if unit=='101' else f'living102_downlights_saved_audit_r{a.revision}.json'
   gate=json.loads((ref/name).read_text());assert gate['pass'] and not gate['errors'] and gate['source_sha256']==meta['candidate_sha256']
  subprocess.run(['python3',str(ROOT/'tools/infinigen/run_bundled_blender.py'),'-t','2','--background','--python-exit-code','1','--python',str(T/'audit_living102_mixed_saved.py'),'--','--revision',str(a.revision)],cwd=ROOT,env=env,check=True)
  gate=json.loads((ref/f'living102_mixed_saved_audit_r{a.revision}.json').read_text())
  assert gate['pass'] and not gate['errors'] and gate['source_sha256']==meta['candidate_sha256']
  d['saved_mixed_lighting_gate']=f'living102_mixed_saved_audit_r{a.revision}.json';save()
 if meta.get('east_photo'):
  subprocess.run(['python3',str(ROOT/'tools/infinigen/run_bundled_blender.py'),'-t','2','--background','--python-exit-code','1','--python',str(T/'audit_east_photo_saved.py'),'--','--revision',str(a.revision)],cwd=ROOT,env=env,check=True)
  gate=json.loads((ref/f'east_photo_saved_audit_r{a.revision}.json').read_text())
  assert gate['pass'] and not gate['errors'] and gate['source_sha256']==meta['candidate_sha256']
  d['saved_east_photo_gate']=f'east_photo_saved_audit_r{a.revision}.json';save()
 if meta.get('real_shower'):
  subprocess.run(['python3',str(ROOT/'tools/infinigen/run_bundled_blender.py'),'-t','4','--background','--python-exit-code','1','--python',str(T/'audit_real_shower_saved.py'),'--','--revision',str(a.revision)],cwd=ROOT,env=env,check=True)
  gate=json.loads((ref/f'real_shower_saved_audit_r{a.revision}.json').read_text())
  assert gate['pass'] and not gate['errors'] and gate['source_sha256']==meta['candidate_sha256']
  d['saved_real_shower_gate']=f'real_shower_saved_audit_r{a.revision}.json';save()
 if meta.get('stone_finish'):
  subprocess.run(['python3',str(ROOT/'tools/infinigen/run_bundled_blender.py'),'-t','4','--background','--python-exit-code','1','--python',str(T/'audit_bathroom_stone_saved.py'),'--','--revision',str(a.revision)],cwd=ROOT,env=env,check=True)
  gate=json.loads((ref/f'bathroom_stone_saved_audit_r{a.revision}.json').read_text())
  assert gate['pass'] and not gate['errors'] and gate['source_sha256']==meta['candidate_sha256']
  d['saved_stone_finish_gate']=f'bathroom_stone_saved_audit_r{a.revision}.json';save()
 d['phase']='rendering';save();subprocess.run(['python3',str(T/'render_residential_furniture.py'),'--revision',str(a.revision),'--views',str(a.views or residential_canonical_path()),'--names',a.names,'--tag',a.tag],cwd=ROOT,env=env,check=True);d['phase']='rendered_visual_review_pending'
except Exception as e:d.update(phase='failed',error=str(e));raise
finally:save()
