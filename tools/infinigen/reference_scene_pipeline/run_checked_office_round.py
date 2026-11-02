"""CPU office trial: saved-source preflights must pass before RGB;never promotes."""
import argparse,subprocess,json,os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];T=Path(__file__).parent
p=argparse.ArgumentParser();p.add_argument('--revision',type=int,required=True);p.add_argument('--tag',required=True);p.add_argument('--names',default='breakout_kitchen');p.add_argument('--views',type=Path);a=p.parse_args()
ref=ROOT/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';state=ref/f'checked_office_round_r{a.revision}.json';assert not state.exists()
d={'pid':os.getpid(),'revision':a.revision,'phase':'saved_preflight','photorealism_accepted':False};env={**os.environ,'CUDA_VISIBLE_DEVICES':''}
def save():state.write_text(json.dumps(d,indent=2));print(json.dumps(d),flush=True)
try:
 save();subprocess.run(['python3',str(T/'run_current_fine_audits.py'),'--scene','office','--revision',str(a.revision)],cwd=ROOT,env=env,check=True)
 for name in ['geometry_audit','wall_overlap_audit','required_spaces_audit','texture_dependencies','functional_assemblies','reception_assembly_audit']:
  q=json.loads((ref/f'{name}_r{a.revision}.json').read_text());assert not q.get('errors'),(name,q.get('errors'))
 # Environment edits require the expected HDR in the saved active world Surface graph.
 meta_path=ref/f'realism_refinement_r{a.revision}.json'
 meta=json.loads(meta_path.read_text()) if meta_path.exists() else {}
 if meta.get('breakout_textile_optical_contract'):
  subprocess.run(['python3',str(ROOT/'tools/infinigen/run_bundled_blender.py'),'-t','2','--background','--python-exit-code','1','--python',str(T/'audit_breakout_textile_saved.py'),'--','--revision',str(a.revision)],cwd=ROOT,env=env,check=True)
  gate=json.loads((ref/f'breakout_textile_saved_audit_r{a.revision}.json').read_text())
  assert gate['pass'] and not gate['errors'] and gate['source_sha256']==meta['candidate_sha256']
  d['saved_breakout_textile_gate']=f'breakout_textile_saved_audit_r{a.revision}.json';save()
 if meta.get('breakout_chair_records'):
  subprocess.run(['python3',str(ROOT/'tools/infinigen/run_bundled_blender.py'),'-t','4','--background','--python-exit-code','1','--python',str(T/'audit_breakout_chairs_saved.py'),'--','--revision',str(a.revision)],cwd=ROOT,env=env,check=True)
  gate=json.loads((ref/f'breakout_chairs_saved_audit_r{a.revision}.json').read_text())
  assert gate['pass'] and not gate['errors'] and gate['source_sha256']==meta['candidate_sha256']
  d['saved_breakout_chair_gate']=f'breakout_chairs_saved_audit_r{a.revision}.json';save()
 # Facade assemblies are not ground furniture. Their explicit classification
 # requires the saved-source pane/opening/frame gate rather than floor support.
 if any(row.get('new_kind')=='architectural_glazing' for row in meta.get('classification_correction',[])):
  subprocess.run(['python3',str(ROOT/'tools/infinigen/run_bundled_blender.py'),'-t','4','--background','--python-exit-code','1','--python',str(T/'audit_east_glazing_saved.py'),'--','--revision',str(a.revision)],cwd=ROOT,env=env,check=True)
  gate=json.loads((ref/f'east_glazing_saved_audit_r{a.revision}.json').read_text())
  assert gate['pass'] and not gate['errors'] and gate['source_sha256']==meta['candidate_sha256']
  d['saved_glazing_gate']=f'east_glazing_saved_audit_r{a.revision}.json';save()
 if meta.get('north_glazing_records'):
  subprocess.run(['python3',str(ROOT/'tools/infinigen/run_bundled_blender.py'),'-t','4','--background','--python-exit-code','1','--python',str(T/'audit_north_glazing_saved.py'),'--','--revision',str(a.revision)],cwd=ROOT,env=env,check=True)
  gate=json.loads((ref/f'north_glazing_saved_audit_r{a.revision}.json').read_text())
  assert gate['pass'] and not gate['errors'] and gate['source_sha256']==meta['candidate_sha256']
  d['saved_north_glazing_gate']=f'north_glazing_saved_audit_r{a.revision}.json';save()
 if 'environment_provenance' in meta:
  expected=Path(meta['environment_provenance']['downloaded_file'])
  source=ROOT/f'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full/scene_candidate_r{a.revision}.blend'
  report=ref/f'world_environment_gate_r{a.revision}.json'
  subprocess.run(['/root/miniconda3/envs/infinigen/bin/python',str(T/'audit_saved_world_environment.py'),'--blend',str(source),'--expected-image',str(expected),'--out',str(report)],cwd=ROOT,env={**env,'OMP_NUM_THREADS':'4'},check=True)
  assert json.loads(report.read_text())['pass']
  d['saved_environment_gate']=str(report.relative_to(ROOT));save()
 d['phase']='rendering';save();cmd=['python3',str(T/'render_breakout_followup.py'),'--revision',str(a.revision),'--names',a.names,'--tag',a.tag]
 if a.views:cmd+=['--views',str(a.views)]
 subprocess.run(cmd,cwd=ROOT,env=env,check=True);d['phase']='rendered_visual_review_pending'
except Exception as e:d.update(phase='failed',error=str(e));raise
finally:save()
