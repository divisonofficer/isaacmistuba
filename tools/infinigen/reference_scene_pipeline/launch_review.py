"""Durable CPU render job; no dependency on an interactive command session."""
import argparse,datetime,json,os,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3]
p=argparse.ArgumentParser();p.add_argument('--scene',choices=['office','residential'],required=True);p.add_argument('--worker',action='store_true');p.add_argument('--revision',type=int);a=p.parse_args()
office=a.scene=='office';scene='commercial_office_floor_02' if office else 'dual_unit_residential_floor_03';revision=a.revision or (17 if office else 18);seed=48712502 if office else 48712503
ref=ROOT/'data/venue_refs/floor_plans_v3'/scene;base=ROOT/'out/infinigen_v2'/f'kr_{scene}_{seed}'/'full';state=ref/f'final_render_job_r{revision}.json';log=ref/f'final_render_job_r{revision}.log'
if not a.worker:
 assert not state.exists(),'Existing job state: inspect rather than duplicate'
 env=os.environ.copy();env['CUDA_VISIBLE_DEVICES']=''
 with log.open('w') as output:process=subprocess.Popen([sys.executable,str(Path(__file__).resolve()),'--scene',a.scene,'--revision',str(revision),'--worker'],stdout=output,stderr=subprocess.STDOUT,env=env,cwd=ROOT,start_new_session=True)
 print(json.dumps({'pid':process.pid,'state':str(state),'log':str(log)}))
else:
 doc={'pid':os.getpid(),'scene':scene,'revision':revision,'phase':'rendering','started_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'device':'CPU','cuda_visible_devices':os.environ.get('CUDA_VISIBLE_DEVICES')};state.write_text(json.dumps(doc,indent=2))
 command=[sys.executable,str(Path(__file__).with_name('render_batch.py')),'--scene',a.scene,'--revision',str(revision),'--blend',str(base/f'scene_review_r{revision}_packed.blend'),'--views',str(base/(f'review_views_delivery_r{revision}.json'))]
 result=subprocess.run(command,cwd=ROOT);doc.update(phase='rendered_visual_review_pending' if result.returncode==0 else 'render_failed',exit_code=result.returncode,finished_at=datetime.datetime.now(datetime.timezone.utc).isoformat());state.write_text(json.dumps(doc,indent=2));sys.exit(result.returncode)
