"""Complete current39 required residential cameras plus explicit diagnostics onCPU,with bounded concurrent batches andmerged receipts.

No visual acceptance orregistry promotion is performed.
"""
import argparse,subprocess,json,os,hashlib,shutil
from pathlib import Path
from full_saved_access_gate import require_current_bathroom_access
from full_view_manifest import residential_canonical_path,residential_required_names,validate_and_normalize
ROOT=Path(__file__).resolve().parents[3];T=Path(__file__).parent
p=argparse.ArgumentParser();p.add_argument('--revision',type=int,required=True);p.add_argument('--workers',type=int,default=4);p.add_argument('--views',type=Path);a=p.parse_args();assert 1<=a.workers<=4
ref=ROOT/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';base=ROOT/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full';source=base/f'scene_candidate_r{a.revision}.blend';out=ref/f'full_suite_r{a.revision}';assert not out.exists()
canonical_path=residential_canonical_path();canonical=json.loads(canonical_path.read_text());views=validate_and_normalize(json.loads(a.views.read_text()) if a.views else canonical,canonical,residential_required_names());names=[v['name'] for v in views];sha=hashlib.sha256(source.read_bytes()).hexdigest();out.mkdir()
(out/'views.json').write_text(json.dumps(views,indent=2));env={**os.environ,'CUDA_VISIBLE_DEVICES':'','OMP_NUM_THREADS':'8'};state=out/'job.json';d={'pid':os.getpid(),'phase':'saved_preflight','revision':a.revision,'source':str(source),'source_sha256':sha,'device':'CPU','required_view_names':names,'canonical_manifest':str(canonical_path),'canonical_manifest_sha256':hashlib.sha256(canonical_path.read_bytes()).hexdigest(),'required_canonical_view_names':[v['name'] for v in canonical],'workers':[],'photorealism_accepted':False}
def save():state.write_text(json.dumps(d,indent=2));print(json.dumps({'phase':d['phase'],'workers':d['workers']}),flush=True)
try:
 save() # Reuse existing current-source reports; never duplicate an active audit or ignore its errors.
 for stem in ['fine_features','required_spaces_audit','texture_dependencies','functional_assemblies','native_toiletry_assembly_audit','wc_layout_audit']:
  report=json.loads((ref/f'{stem}_r{a.revision}.json').read_text());assert 'errors' in report and not report['errors'],(stem,report.get('errors'));assert report['source_sha256']==sha,(stem,'stale source')
  if stem=='functional_assemblies':assert report.get('auditor_sha256')==hashlib.sha256((T/'audit_functional_assemblies.py').read_bytes()).hexdigest(),(stem,'stale auditor')
  if stem=='native_toiletry_assembly_audit':assert report.get('auditor_sha256')==hashlib.sha256((T/'audit_native_toiletries.py').read_bytes()).hexdigest(),(stem,'stale auditor')
  if stem=='wc_layout_audit':
   assert report.get('auditor_sha256')==hashlib.sha256((T/'audit_wc_layout.py').read_bytes()).hexdigest(),(stem,'stale auditor')
   assert report.get('helper_sha256')==hashlib.sha256((T/'wc_layout_checks.py').read_bytes()).hexdigest(),(stem,'stale helper')
   assert report.get('compact_contract_helper_sha256')==hashlib.sha256((T/'compact_wc_contract.py').read_bytes()).hexdigest(),(stem,'stale compact contract helper')
 d['bathroom_access_gate']=require_current_bathroom_access(ref,a.revision,sha);save()
 children=[];logs=[];d['phase']='rendering'
 for i in range(a.workers):
  folder=out/f'batch_{i}';folder.mkdir();vf=folder/'views.json';vf.write_text(json.dumps(views[i::a.workers],indent=2));log=(folder/'render.log').open('w');logs.append(log)
  command=['python3',str(ROOT/'tools/infinigen/run_bundled_blender.py'),'-t','8','--background',str(source),'--python-exit-code','1','--python',str(T/'render.py'),'--','--views',str(vf),'--out',str(folder/'candidate'),'--width','1280','--samples','48','--threads','8']
  child=subprocess.Popen(command,cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT);children.append(child);d['workers'].append({'batch':i,'pid':child.pid,'views':[v['name'] for v in views[i::a.workers]]});save()
 codes=[child.wait() for child in children]
 for log in logs:log.close()
 assert all(c==0 for c in codes),codes
 candidate=out/'candidate';candidate.mkdir();frames={};merged=None;receipts=[]
 for i in range(a.workers):
  rp=out/f'batch_{i}/candidate/render_receipt.json';receipt=json.loads(rp.read_text());assert receipt['source_sha256']==sha and receipt['source_unchanged']
  if merged is None:merged=dict(receipt)
  else:assert receipt['renderer_sha256']==merged['renderer_sha256'] and receipt['lighting_policy']==merged['lighting_policy']
  receipts.append(str(rp))
  for frame in receipt['frames']:
   name=frame['name'];assert name not in frames;old=Path(frame['path']);assert hashlib.sha256(old.read_bytes()).hexdigest()==frame['sha256'];target=candidate/(name+'.png');shutil.copy2(old,target);frame['path']=str(target);frames[name]=frame
 assert set(frames)==set(names);assert hashlib.sha256(source.read_bytes()).hexdigest()==sha
 merged.update(frames=[frames[n] for n in names],batch_receipts=receipts,phase='rendered_visual_review_pending',source_unchanged=True,visual_acceptance=False);(candidate/'render_receipt.json').write_text(json.dumps(merged,indent=2));d.update(phase=f'rendered_full{len(frames)}_visual_review_pending',render_exit_codes=codes,rendered_view_count=len(frames))
except Exception as e:d.update(phase='failed',error=str(e));raise
finally:save()
