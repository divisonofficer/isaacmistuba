import json,os,subprocess,time
from pathlib import Path
R=Path(__file__).resolve().parents[3];T=Path(__file__).parent;B=R/'data/venue_refs/floor_plans_v3';D=B/'shared_dining_residence_05';Q=D/'slots04_05_metric_r6_ab_queue.json';assert not Q.exists()
for scene in ['rural_stone_cottage_04','shared_dining_residence_05']:assert json.loads((B/scene/'candidate_r5_cpu/job.json').read_text()).get('exit_code')==0,'Do not interrupt preserved R5'
s={'pid':os.getpid(),'phase':'starting','started_unix':time.time(),'device':'CPU','threads':2,'scope':'One metric-only native floor A/B: same R5 views/lights/exposure/material role, only native Brick Width/Row Height corrected','jobs':[]}
def save():Q.write_text(json.dumps(s,indent=2))
def run(label,cmd,log):
 s['phase']=label
 with log.open('w') as f:
  p=subprocess.Popen(cmd,cwd=R,env={**os.environ,'CUDA_VISIBLE_DEVICES':''},stdout=f,stderr=subprocess.STDOUT);row={'label':label,'child_pid':p.pid,'argv':cmd,'phase':'live'};s['jobs'].append(row);save();code=p.wait();row.update(phase='finished',exit_code=code);save()
 if code:s.update(phase='failed',finished_unix=time.time());save();raise SystemExit(code)
save();run('metric_native_parameter_build',['python3',str(T/'slots04_05_observed_build.py'),'--script',str(T/'slots04_05_metric_floor_r6.py'),'--job-dir',str(D/'metric_r6_build')],D/'metric_r6_build_manager.log')
for scene,seed,slot in [('shared_dining_residence_05',48712505,'05'),('rural_stone_cottage_04',48712504,'04')]:
 d=B/scene;blend=R/'out/infinigen_v2'/f'kr_{scene}_{seed}'/'full'/f'scene_candidate_slots{slot}_r6_metric.blend';run('metric_render_'+scene,['python3',str(T/'run_observed_render.py'),'--blend',str(blend),'--views',str(d/'candidate_r6_metric_views.json'),'--out',str(d/'candidate_r6_metric_cpu/render'),'--threads','2','--samples','32'],d/'candidate_r6_metric_manager.log')
s.update(phase='finished',finished_unix=time.time());save()
