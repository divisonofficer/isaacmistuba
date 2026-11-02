"""Run current packed-source checks, preserving hash-bound receipts per revision."""
import argparse,datetime,hashlib,json,os,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];p=argparse.ArgumentParser();p.add_argument('--scene',choices=['office','residential'],required=True);p.add_argument('--revision',type=int,required=True);a=p.parse_args();office=a.scene=='office';scene='commercial_office_floor_02' if office else 'dual_unit_residential_floor_03';seed=48712502 if office else 48712503;rev=a.revision;ref=ROOT/'data/venue_refs/floor_plans_v3'/scene;blend=ROOT/'out/infinigen_v2'/f'kr_{scene}_{seed}'/'full'/f'scene_review_r{rev}_packed.blend';sha=hashlib.sha256(blend.read_bytes()).hexdigest();python='/root/miniconda3/envs/infinigen/bin/python';env=os.environ.copy();env['CUDA_VISIBLE_DEVICES']='';doc={'pid':os.getpid(),'source':str(blend),'source_sha256':sha,'phase':'checking','checks':[]};state=ref/f'delivery_audits_r{rev}.json'
checks=[('geometry', ['--scene',scene]),('materials',[]),('circulation',['--reference',str(ref)]),('native_doors',[])]+([] if office else [('headroom',[])])
for name,extra in checks:
 out=ref/f'{name}_delivery_audit_r{rev}.json';log=ref/f'{name}_delivery_audit_r{rev}.log';script=Path(__file__).with_name('audit_'+name+'.py')
 command=[python,str(script),'--','--blend',str(blend),'--out',str(out)]+extra;state.write_text(json.dumps(doc,indent=2))
 if out.exists():assert json.loads(out.read_text())['source_sha256']==sha
 else:
  with log.open('w') as f:subprocess.run(command,cwd=ROOT,env=env,stdout=f,stderr=subprocess.STDOUT,check=True)
 record=json.loads(out.read_text());assert record.get('source_sha256',sha)==sha
 good=not record.get('errors') and not record.get('failures')
 if name=='headroom':good=record.get('all_pass',record.get('pass',False))
 doc['checks'].append({'name':name,'path':str(out),'pass':good});state.write_text(json.dumps(doc,indent=2));print(json.dumps(doc['checks'][-1]),flush=True)
assert hashlib.sha256(blend.read_bytes()).hexdigest()==sha;doc.update(phase='passed_bounded_checks' if all(r['pass'] for r in doc['checks']) else 'needs_correction',finished_at=datetime.datetime.now(datetime.timezone.utc).isoformat());state.write_text(json.dumps(doc,indent=2))
