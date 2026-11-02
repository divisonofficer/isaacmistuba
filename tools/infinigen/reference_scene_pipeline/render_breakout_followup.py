"""Current breakout wide plus closeups; source-bound receipts, CPU only."""
import argparse,os,subprocess,json,datetime
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];p=argparse.ArgumentParser();p.add_argument('--revision',type=int,required=True);p.add_argument('--names',default='');p.add_argument('--views',type=Path);p.add_argument('--tag',default='');p.add_argument('--preserve-source-lighting',action='store_true');a=p.parse_args();base=ROOT/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full';ref=ROOT/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';out=ref/(f'breakout_r{a.revision}'+('_'+a.tag if a.tag else ''));out.mkdir(exist_ok=True);state=out/'job.json';assert not state.exists();views=[v for v in json.loads((base/'review_views_delivery_r23.json').read_text()) if v['name']=='breakout_kitchen'];views += [{'name':'breakout_chair_detail','location':[11.0,2.25,1.15],'target':[11.85,2.96,.72],'hfov':52},{'name':'breakout_sink_detail','location':[12.85,4.20,1.60],'target':[14.35,4.70,1.10],'hfov':48},{'name':'coffee_machine_detail','location':[13.35,5.1,1.42],'target':[14.16,5.65,1.20],'hfov':48}]
views.append({'name':'breakout_sink_drain_detail','location':[13.15,4.25,1.90],'target':[14.275,4.65,.97],'hfov':48})
if a.views:views=json.loads(a.views.read_text())
if a.names:views=[v for v in views if v['name'] in a.names.split(',')]
assert views,'No requested render views found'
if a.names:assert {v['name'] for v in views}==set(a.names.split(',')),'Requested view names missing'
for v in views:v['render_width']=1024 if v['name']=='breakout_kitchen' else 1280;v['samples']=48
vf=out/'views.json';vf.write_text(json.dumps(views,indent=2));d={'pid':os.getpid(),'phase':'rendering','device':'CPU','revision':a.revision,'started_at':datetime.datetime.now(datetime.timezone.utc).isoformat()};state.write_text(json.dumps(d,indent=2));source=base/f'scene_candidate_r{a.revision}.blend';cmd=['python3',str(ROOT/'tools/infinigen/run_bundled_blender.py'),'-t','8','--background',str(source),'--python-exit-code','1','--python',str(Path(__file__).with_name('render.py')),'--','--views',str(vf),'--out',str(out/'candidate'),'--width','1024','--samples','48']
if a.preserve_source_lighting:cmd.append('--preserve-source-lighting')
try:
 with (out/'render.log').open('w') as f:subprocess.run(cmd,cwd=ROOT,env=dict(os.environ,CUDA_VISIBLE_DEVICES=''),stdout=f,stderr=subprocess.STDOUT,check=True)
 d['phase']='rendered_visual_review_pending'
except Exception as e:d['phase']='failed';d['error']=str(e);raise
finally:d['updated_at']=datetime.datetime.now(datetime.timezone.utc).isoformat();state.write_text(json.dumps(d,indent=2))
