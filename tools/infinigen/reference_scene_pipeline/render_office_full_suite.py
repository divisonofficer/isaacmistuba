"""Complete current16-camera office suite onCPU,with bounded concurrent batches andmerged receipts.

No visual acceptance orregistry promotion is performed.
"""
import argparse,subprocess,json,os,hashlib,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];T=Path(__file__).parent
p=argparse.ArgumentParser();p.add_argument('--revision',type=int,required=True);p.add_argument('--workers',type=int,default=4);a=p.parse_args();assert 1<=a.workers<=4
ref=ROOT/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';base=ROOT/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full';source=base/f'scene_candidate_r{a.revision}.blend';out=ref/f'full_suite_r{a.revision}';assert not out.exists();out.mkdir()
sha=hashlib.sha256(source.read_bytes()).hexdigest();views=json.loads((base/'review_views_delivery_r23.json').read_text());names=[v['name'] for v in views];assert len(names)==16 and len(set(names))==16
for v in views:v['render_width']=2048 if v.get('overview') else 1024 if v['name']=='breakout_kitchen' else 1280;v['samples']=48
(out/'views.json').write_text(json.dumps(views,indent=2));env={**os.environ,'CUDA_VISIBLE_DEVICES':'','OMP_NUM_THREADS':'8'};state=out/'job.json';d={'pid':os.getpid(),'phase':'saved_preflight','revision':a.revision,'source':str(source),'source_sha256':sha,'device':'CPU','required_view_names':names,'workers':[],'photorealism_accepted':False}
def save():state.write_text(json.dumps(d,indent=2));print(json.dumps({'phase':d['phase'],'workers':d['workers']}),flush=True)
try:
 save()
 stems=['geometry_audit','required_spaces_audit','texture_dependencies','functional_assemblies','reception_assembly_audit']
 reusable=all((ref/f'{stem}_r{a.revision}.json').exists() for stem in stems)
 if reusable:
  reports=[json.loads((ref/f'{stem}_r{a.revision}.json').read_text()) for stem in stems]
  reusable=all(report.get('source_sha256')==sha and 'errors' in report for report in reports) and reports[3].get('auditor_sha256')==hashlib.sha256((T/'audit_functional_assemblies.py').read_bytes()).hexdigest() and reports[4].get('auditor_sha256')==hashlib.sha256((T/'audit_reception_assembly.py').read_bytes()).hexdigest()
 if not reusable:
  subprocess.run(['python3',str(T/'run_current_fine_audits.py'),'--scene','office','--revision',str(a.revision)],cwd=ROOT,env=env,check=True)
 for stem in stems:
  report=json.loads((ref/f'{stem}_r{a.revision}.json').read_text());assert report.get('source_sha256')==sha,(stem,'stale source');assert 'errors' in report and not report['errors'],(stem,report.get('errors'))
 d['source_bound_audits_reused']=reusable
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
 merged.update(frames=[frames[n] for n in names],batch_receipts=receipts,phase='rendered_visual_review_pending',source_unchanged=True,visual_acceptance=False);(candidate/'render_receipt.json').write_text(json.dumps(merged,indent=2));d.update(phase='rendered_full16_visual_review_pending',render_exit_codes=codes,rendered_view_count=len(frames))
except Exception as e:d.update(phase='failed',error=str(e));raise
finally:save()
