"""Durable CPU build -> saved geometry/environment gates -> fixed-view RGB. No adoption."""
import argparse,json,os,subprocess
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--revision',type=int,required=True);p.add_argument('--names',default='breakout_kitchen,private_office,conference_reference_reverse');p.add_argument('--bundled-builder',action='store_true');a=p.parse_args();root=Path(__file__).resolve().parents[3];t=Path(__file__).parent;ref=root/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';base=root/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full';state=ref/f'environment_trial_r{a.revision}.json';builder=t/f'refine_office_environment_r{a.revision}.py';assert builder.exists();assert not state.exists();assert not (base/f'scene_candidate_r{a.revision}.blend').exists();env={**os.environ,'CUDA_VISIBLE_DEVICES':'','OMP_NUM_THREADS':'4'};d={'pid':os.getpid(),'revision':a.revision,'phase':'building','device':'CPU','photorealism_accepted':False}
def save():state.write_text(json.dumps(d,indent=2)+'\n');print(json.dumps(d),flush=True)
try:
 save();subprocess.run((['python3',str(root/'tools/infinigen/run_bundled_blender.py'),'-t','4','--background','--python-exit-code','1','--python',str(builder)] if a.bundled_builder else ['/root/miniconda3/envs/infinigen/bin/python',str(builder)]),cwd=root,env=env,check=True);d['phase']='checked_preflight_then_rgb';save();subprocess.run(['python3',str(t/'run_checked_office_round.py'),'--revision',str(a.revision),'--tag','environment','--views',str(base/'review_views_delivery_r23.json'),'--names',a.names],cwd=root,env=env,check=True);d['phase']='rendered_visual_review_pending'
except Exception as e:d.update(phase='failed',error=str(e));raise
finally:save()
