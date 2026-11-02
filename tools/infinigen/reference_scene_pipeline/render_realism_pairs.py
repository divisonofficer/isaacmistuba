"""Fixed-camera baseline/candidate comparison, CPU until an explicit GPU lease exists."""
import argparse,datetime,hashlib,json,os,shutil,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];p=argparse.ArgumentParser();p.add_argument('--scene',choices=['office','residential'],required=True);p.add_argument('--worker',action='store_true');p.add_argument('--revision',type=int);p.add_argument('--reuse-baseline',type=int);a=p.parse_args();office=a.scene=='office';scene='commercial_office_floor_02' if office else 'dual_unit_residential_floor_03';seed=48712502 if office else 48712503;old,default_rev=(18,20) if office else (22,24);rev=a.revision or default_rev;ref=ROOT/'data/venue_refs/floor_plans_v3'/scene;base=ROOT/'out/infinigen_v2'/f'kr_{scene}_{seed}/full';out=ref/f'realism_r{rev}';state=ref/f'realism_pair_job_r{rev}.json';log=ref/f'realism_pair_job_r{rev}.log';env=os.environ.copy();env['CUDA_VISIBLE_DEVICES']=''
if not a.worker:
 assert not state.exists(),'Inspect existing comparison job before retrying'
 with log.open('w') as f:proc=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'--scene',a.scene,'--revision',str(rev),'--reuse-baseline',str(a.reuse_baseline or 0),'--worker'],stdout=f,stderr=subprocess.STDOUT,env=env,cwd=ROOT,start_new_session=True)
 print(json.dumps({'pid':proc.pid,'state':str(state)}));sys.exit()
state.write_text(json.dumps({'pid':os.getpid(),'phase':'rendering','device':'CPU','revision':rev,'started_at':datetime.datetime.now(datetime.timezone.utc).isoformat()},indent=2));out.mkdir(exist_ok=True)
records=json.loads((base/f'review_views_delivery_r{old}.json').read_text());wanted=['breakout_kitchen','library_coffee_cups_close'] if office else ['101_dressing_context','102_dressing_context']+(['101_bathroom_wc_reverse','102_bathroom_wc_reverse'] if rev>=26 else []);views=[v for v in records if v['name'] in wanted]
new={'name':'coffee_machine_detail','location':[13.35,5.1,1.42],'target':[14.16,5.65,1.20],'hfov':48} if office else {'name':'garment_mesh_detail','location':[4.1,13.3,1.55],'target':[4.1,12.43,1.5],'hfov':55};views.append(new);viewfile=out/'views.json';viewfile.write_text(json.dumps(views,indent=2));receipt=json.loads((ref/f'renders/r{old}/render_receipt.json').read_text());baseline=out/'baseline';baseline.mkdir(exist_ok=True)
for f in receipt['frames']:
 if f['name'] not in wanted:continue
 path=Path(f['path']);assert hashlib.sha256(path.read_bytes()).hexdigest()==f['sha256'];shutil.copy2(path,baseline/path.name)
commands=[]
tasks=[(base/f'scene_review_r{old}_packed.blend',out/'baseline_new',new['name']),(base/f'scene_candidate_r{rev}.blend',out/'candidate',','.join(v['name'] for v in views))]
if a.reuse_baseline:
 previous=ref/f'realism_r{a.reuse_baseline}';proof=json.loads((previous/'baseline_new/render_receipt.json').read_text());assert proof['source_sha256']==receipt['source_sha256'] and proof['source_unchanged'];frame=next(f for f in proof['frames'] if f['name']==new['name']);path=previous/'baseline'/(new['name']+'.png');assert hashlib.sha256(path.read_bytes()).hexdigest()==frame['sha256'];shutil.copy2(path,baseline/path.name);tasks=tasks[1:]
for source,dest,names in tasks:
 command=['python3',str(ROOT/'tools/infinigen/run_bundled_blender.py'),'-t','8','--background',str(source),'--python-exit-code','1','--python',str(Path(__file__).with_name('render.py')),'--','--views',str(viewfile),'--out',str(dest),'--names',names,'--width','1024' if office else '800','--samples','32' if office else '24']
 with (out/(dest.name+'.log')).open('w') as f:subprocess.run(command,stdout=f,stderr=subprocess.STDOUT,env=env,cwd=ROOT,check=True)
 if dest.name=='baseline_new':shutil.copy2(dest/(new['name']+'.png'),baseline/(new['name']+'.png'))
doc=json.loads(state.read_text());doc.update(phase='rendered_visual_review_pending',finished_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),views=[v['name'] for v in views],baseline_revision=old,candidate_revision=rev);state.write_text(json.dumps(doc,indent=2));print(json.dumps(doc),flush=True)
