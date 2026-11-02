"""Durable fixed-camera CPU comparison for blind-review corrections."""
import argparse,json,os,subprocess,datetime,hashlib,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];p=argparse.ArgumentParser();p.add_argument('--scene',choices=['office','residential'],required=True);p.add_argument('--revision',type=int);p.add_argument('--baseline-revision',type=int);p.add_argument('--reuse-baseline-dir',type=Path);a=p.parse_args();office=a.scene=='office';scene='commercial_office_floor_02' if office else 'dual_unit_residential_floor_03';seed=48712502 if office else 48712503;rev=a.revision or (26 if office else 32);old=a.baseline_revision or (24 if office else 30);base=ROOT/'out/infinigen_v2'/f'kr_{scene}_{seed}/full';ref=ROOT/'data/venue_refs/floor_plans_v3'/scene;out=ref/f'realism_r{rev}';out.mkdir(exist_ok=True);state=ref/f'realism_pair_job_r{rev}.json';assert not state.exists();env=os.environ.copy();env['CUDA_VISIBLE_DEVICES']='';names=['private_office'] if office else ['101_bathroom','101_ensuite_wetroom_review'];viewrev=23 if office else 30;views=[v for v in json.loads((base/f'review_views_delivery_r{viewrev}.json').read_text()) if v['name'] in names];assert len(views)==len(names)
for v in views:v['render_width']=1024;v['samples']=32
if office:
 views.append({'name':'private_electronics_detail','location':[2.42,4.18,1.45],'target':[1.47,4.25,1.0],'hfov':48,'render_width':1024,'samples':32})
viewfile=out/'views.json';viewfile.write_text(json.dumps(views,indent=2));d={'pid':os.getpid(),'phase':'rendering','device':'CPU','revision':rev,'baseline_revision':old,'started_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'views':[v['name'] for v in views]};state.write_text(json.dumps(d,indent=2))
try:
 for label in ['baseline','candidate']:
  source=base/(f'scene_candidate_r{old}.blend' if office else f'scene_review_r{old}_packed.blend') if label=='baseline' else base/f'scene_candidate_r{rev}.blend'
  if label=='baseline' and a.reuse_baseline_dir:
   proof=json.loads((a.reuse_baseline_dir/'render_receipt.json').read_text());assert proof['source_unchanged'] and proof['source_sha256']==hashlib.sha256(source.read_bytes()).hexdigest();dest=out/label;dest.mkdir(exist_ok=True)
   for v in views:
    f=next(f for f in proof['frames'] if f['name']==v['name']);path=a.reuse_baseline_dir/(v['name']+'.png');assert hashlib.sha256(path.read_bytes()).hexdigest()==f['sha256'];shutil.copy2(path,dest/path.name)
   (dest/'reused_receipt.json').write_text(json.dumps(proof,indent=2));continue
  command=['python3',str(ROOT/'tools/infinigen/run_bundled_blender.py'),'-t','8','--background',str(source),'--python-exit-code','1','--python',str(Path(__file__).with_name('render.py')),'--','--views',str(viewfile),'--out',str(out/label),'--width','1024','--samples','32']
  with (out/(label+'.log')).open('w') as f:subprocess.run(command,cwd=ROOT,env=env,stdout=f,stderr=subprocess.STDOUT,check=True)
 d['phase']='rendered_visual_review_pending'
except Exception as exc:d['phase']='failed';d['error']=str(exc);raise
finally:d['updated_at']=datetime.datetime.now(datetime.timezone.utc).isoformat();state.write_text(json.dumps(d,indent=2))
