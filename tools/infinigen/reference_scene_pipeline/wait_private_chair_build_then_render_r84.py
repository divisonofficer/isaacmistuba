"""Observe one known live build, then preflight/render once. Never restart a missing build."""
import pathlib,json,os,time,subprocess
root=pathlib.Path(__file__).resolve().parents[3];t=pathlib.Path(__file__).parent;ref=root/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';base=root/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full';builder=349843;state=ref/'private_chair_r84_checked_workflow.json';assert not state.exists();d={'pid':os.getpid(),'builder_pid':builder,'phase':'observing_existing_build','device':'CPU','photorealism_accepted':False}
def save():state.write_text(json.dumps(d,indent=2)+'\n');print(json.dumps(d),flush=True)
def live():
 p=pathlib.Path(f'/proc/{builder}')
 if not p.exists():return False
 stat=(p/'stat').read_text().split(') ',1)[1].split()[0]
 if stat=='Z':return False
 cmd=(p/'cmdline').read_bytes();return b'refine_private_product_chair_r84.py' in cmd
try:
 save();deadline=time.monotonic()+1800
 while live():
  if time.monotonic()>deadline:raise TimeoutError('Known builder still live;no retry/restart authorized bytimeout')
  time.sleep(5)
 assert (ref/'realism_refinement_r84.json').exists(),'Builder ended without finalrefinement evidence;do not render orrestart'
 assert (base/'scene_candidate_r84.blend').exists();d['phase']='checked_preflight_then_rgb';save();subprocess.run(['python3',str(t/'run_checked_office_round.py'),'--revision','84','--tag','private_product_chair','--views',str(base/'review_views_private_chair_r84.json'),'--names','private_office,private_office_chair_front_detail'],cwd=root,env={**os.environ,'CUDA_VISIBLE_DEVICES':''},check=True);d['phase']='rendered_visual_review_pending'
except Exception as e:d.update(phase='failed',error=str(e));raise
finally:save()
