import json,os,subprocess,time
from pathlib import Path
R=Path(__file__).resolve().parents[3];B=R/'data/venue_refs/floor_plans_v3';Q=B/'shared_dining_residence_05/slots04_05_cpu_queue.json';assert not Q.exists();state={'pid':os.getpid(),'device':'CPU','threads':2,'phase':'waiting_existing_rural_r1','jobs':[]}
def save():Q.write_text(json.dumps(state,indent=2))
save();previous=B/'rural_stone_cottage_04/candidate_r1_cpu/job.json'
while json.loads(previous.read_text())['phase'] in ['starting','live']:time.sleep(2)
for scene,seed,slot in [('shared_dining_residence_05',48712505,'05'),('rural_stone_cottage_04',48712504,'04')]:
 d=B/scene;blend=R/'out/infinigen_v2'/f'kr_{scene}_{seed}'/'full'/f'scene_candidate_slots{slot}_r2.blend';out=d/'candidate_r2_cpu/render';cmd=['python3',str(R/'tools/infinigen/reference_scene_pipeline/run_observed_render.py'),'--blend',str(blend),'--views',str(d/'candidate_r1_views.json'),'--out',str(out),'--threads','2','--samples','32'];state['phase']='rendering_'+scene
 with (d/'candidate_r2_manager.log').open('w') as log:
  p=subprocess.Popen(cmd,cwd=R,env={**os.environ,'CUDA_VISIBLE_DEVICES':''},stdout=log,stderr=subprocess.STDOUT);row={'scene_id':scene,'child_pid':p.pid,'argv':cmd,'phase':'live'};state['jobs'].append(row);save();code=p.wait();row.update(phase='finished',exit_code=code);save()
state['phase']='finished';save()
