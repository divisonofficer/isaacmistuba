"""Durable CPU coordinator launch, detached from interactive execution lifetime.
Existing output orlaunch records are never overwritten orautomatically restarted.
"""
import argparse,json,subprocess,os,sys,datetime
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];T=Path(__file__).parent
p=argparse.ArgumentParser();p.add_argument('--scene',choices=['office','residential'],required=True);p.add_argument('--revision',type=int,required=True);p.add_argument('--workers',type=int,default=4);p.add_argument('--views',type=Path);a=p.parse_args();assert 1<=a.workers<=4
scene='commercial_office_floor_02' if a.scene=='office' else 'dual_unit_residential_floor_03';seed=48712502 if a.scene=='office' else 48712503;ref=ROOT/'data/venue_refs/floor_plans_v3'/scene;source=ROOT/'out/infinigen_v2'/f'kr_{scene}_{seed}/full'/f'scene_candidate_r{a.revision}.blend';assert source.is_file();out=ref/f'full_suite_r{a.revision}';assert not out.exists(),'Existing full suite requires observation/recovery,not relaunch';record=ref/f'full_suite_launch_r{a.revision}.json';logpath=ref/f'full_suite_coordinator_r{a.revision}.log';driver=T/('render_office_full_suite.py' if a.scene=='office' else 'render_residential_full_suite.py');assert driver.is_file();command=[sys.executable,str(driver),'--revision',str(a.revision),'--workers',str(a.workers)]
if a.views:
 assert a.scene=='residential','Custom suite views supported for residential only'
 command+=['--views',str(a.views.resolve())]
with record.open('x') as f:json.dump({'phase':'launching','source':str(source),'command':command},f,indent=2)
with logpath.open('x') as log:
 child=subprocess.Popen(command,cwd=ROOT,env={**os.environ,'CUDA_VISIBLE_DEVICES':'','OMP_NUM_THREADS':'8'},stdin=subprocess.DEVNULL,stdout=log,stderr=subprocess.STDOUT,start_new_session=True,close_fds=True)
os.kill(child.pid,0);record.write_text(json.dumps({'phase':'coordinator_launched_not_render_complete','pid':child.pid,'source':str(source),'command':command,'log':str(logpath),'job':str(out/'job.json'),'start_new_session':True,'CPU_only':True,'started_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'photorealism_accepted':False},indent=2));print(record.read_text(),flush=True)
