"""Small controlled light-balance trial before committing another full scene round."""
import argparse,subprocess,os,json,hashlib,shutil,datetime
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];p=argparse.ArgumentParser();p.add_argument('--scene',choices=['office','residential'],required=True);a=p.parse_args();office=a.scene=='office';scene='commercial_office_floor_02' if office else 'dual_unit_residential_floor_03';seed=48712502 if office else 48712503;old,rev=(24,25) if office else (30,31);viewrev=23 if office else 30;base=ROOT/'out/infinigen_v2'/f'kr_{scene}_{seed}/full';ref=ROOT/'data/venue_refs/floor_plans_v3'/scene;out=ref/f'realism_r{rev}';assert not (out/'candidate/render_receipt.json').exists();out.mkdir(exist_ok=True);wanted=['open_workplace_reference_wide','breakout_kitchen'] if office else ['101_living','101_master','101_dressing_context'];views=[v for v in json.loads((base/f'review_views_delivery_r{viewrev}.json').read_text()) if v['name'] in wanted];viewfile=out/'views.json';viewfile.write_text(json.dumps(views,indent=2));state=ref/f'realism_light_job_r{rev}.json';state.write_text(json.dumps({'pid':os.getpid(),'phase':'rendering','device':'CPU','experiment':'unchanged geometry/material/world/exposure; ceiling-to-window ratio only'},indent=2));env=os.environ.copy();env['CUDA_VISIBLE_DEVICES']='';tasks=[]
if office:tasks.append((base/f'scene_candidate_r{old}.blend',out/'baseline'))
else:
 before=out/'baseline';before.mkdir(exist_ok=True);receipt=json.loads((ref/'renders/r30/render_receipt.json').read_text());assert receipt['source_unchanged']
 for f in receipt['frames']:
  if f['name'] in wanted:
   src=Path(f['path']);assert hashlib.sha256(src.read_bytes()).hexdigest()==f['sha256'];shutil.copy2(src,before/src.name)
tasks.append((base/f'scene_candidate_r{rev}.blend',out/'candidate'))
for source,dest in tasks:
 command=['python3',str(ROOT/'tools/infinigen/run_bundled_blender.py'),'-t','8','--background',str(source),'--python-exit-code','1','--python',str(Path(__file__).with_name('render.py')),'--','--views',str(viewfile),'--out',str(dest),'--width','1024' if office else '800','--samples','32' if office else '24']
 with (out/(dest.name+'.log')).open('w') as f:subprocess.run(command,cwd=ROOT,env=env,stdout=f,stderr=subprocess.STDOUT,check=True)
d=json.loads(state.read_text());d.update(phase='rendered_visual_review_pending',finished_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),views=wanted);state.write_text(json.dumps(d,indent=2));print(json.dumps(d),flush=True)
