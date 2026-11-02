"""Low-cost gross-shape gate before spending a full closeup render."""
import argparse,json,subprocess,os,datetime
from pathlib import Path
p=argparse.ArgumentParser();p.add_argument('--revision',type=int,required=True);a=p.parse_args();ROOT=Path(__file__).resolve().parents[3];base=ROOT/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full';ref=ROOT/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';out=ref/f'garment_pilot_r{a.revision}';out.mkdir(exist_ok=True);state=out/'job.json';assert not state.exists();v=next(v for v in json.loads((base/'review_views_delivery_r30.json').read_text()) if v['name']=='garment_mesh_detail');v.update(location=[4.1,13.5,1.5],target=[4.1,12.43,1.45],hfov=75,render_width=640,samples=8);vf=out/'views.json';vf.write_text(json.dumps([v],indent=2));d={'pid':os.getpid(),'phase':'rendering','device':'CPU','revision':a.revision,'purpose':'640px8spp gross-shape pilot,not fine material acceptance','started_at':datetime.datetime.now(datetime.timezone.utc).isoformat()};state.write_text(json.dumps(d,indent=2))
try:
 cmd=['python3',str(ROOT/'tools/infinigen/run_bundled_blender.py'),'-t','8','--background',str(base/f'scene_candidate_r{a.revision}.blend'),'--python-exit-code','1','--python',str(Path(__file__).with_name('render.py')),'--','--views',str(vf),'--out',str(out/'candidate'),'--width','640','--samples','8'];
 with (out/'render.log').open('w') as f:subprocess.run(cmd,cwd=ROOT,env=dict(os.environ,CUDA_VISIBLE_DEVICES=''),stdout=f,stderr=subprocess.STDOUT,check=True)
 d['phase']='pilot_visual_review_pending'
except Exception as e:d['phase']='failed';d['error']=str(e);raise
finally:d['updated_at']=datetime.datetime.now(datetime.timezone.utc).isoformat();state.write_text(json.dumps(d,indent=2))
