"""Serialize reviewed-construction candidates after r002;never duplicate live jobs."""
import os,json,time,subprocess,traceback
from pathlib import Path
R=Path(__file__).resolve().parents[3];T=Path(__file__).parent;BASE=R/'data/venue_refs/floor_plans_v3';receipt=BASE/'skyline_penthouse_08/render_queue_calibrated.json';assert not receipt.exists();j={'pid':os.getpid(),'device':'CPU','threads':2,'phase':'waiting_previous_queue','jobs':[]};receipt.write_text(json.dumps(j,indent=2))
def save():receipt.write_text(json.dumps(j,indent=2))
try:
 prev=BASE/'skyline_penthouse_08/render_queue_r005.json'
 while json.loads(prev.read_text()).get('phase')not in ['finished','failed']:time.sleep(3)
 for scene,seed,rev in [('double_height_duplex_09',48712509,'r006'),('skyline_penthouse_08',48712508,'r007')]:
  d=BASE/scene;b=R/'out/infinigen_v2'/f'kr_{scene}_{seed}/full'/f'scene_candidate_{rev}.blend'
  while not b.exists() or not(d/f'views_{rev}.json').exists() or json.loads((d/f'build_{rev}_job.json').read_text()).get('phase')!='saved_fixture_transport_verified_render_pending':
   status=d/f'build_{rev}_job.json'
   if status.exists()and json.loads(status.read_text()).get('phase')=='failed':raise RuntimeError(str(status))
   time.sleep(3)
  row={'scene_id':scene,'revision':rev,'phase':'starting','started_unix':time.time()};j['jobs'].append(row);j['phase']='rendering';save()
  cmd=['python3',str(T/'run_observed_render.py'),'--blend',str(b),'--views',str(d/f'views_{rev}.json'),'--out',str(d/f'render_{rev}/frames'),'--threads','2','--samples','32','--preserve-source-lighting']
  with(d/f'render_{rev}_manager.log').open('w')as f:
   p=subprocess.Popen(cmd,stdout=f,stderr=subprocess.STDOUT,env={**os.environ,'CUDA_VISIBLE_DEVICES':'','OMP_NUM_THREADS':'2','OPENBLAS_NUM_THREADS':'2'});row.update(pid=p.pid,phase='live');save();code=p.wait()
  row.update(exit_code=code,phase='rendered_direct_review_pending'if code==0 else'failed',finished_unix=time.time());save()
  subprocess.run(['python3',str(T/'slots08_09_refresh.py')],check=True)
 j['phase']='finished';save()
except BaseException as e:j.update(phase='failed',error=repr(e),traceback=traceback.format_exc());save();raise
