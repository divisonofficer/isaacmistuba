"""Source-bound residential furniture comparisons, exact shared review cameras, CPU only."""
import argparse,datetime,json,os,subprocess
from pathlib import Path
from full_view_manifest import residential_canonical_path
ROOT=Path(__file__).resolve().parents[3];p=argparse.ArgumentParser();p.add_argument('--revision',type=int,required=True);p.add_argument('--views',type=Path);p.add_argument('--tag',default='');p.add_argument('--preserve-source-lighting',action='store_true');p.add_argument('--names',default='101_sofa_material_close');a=p.parse_args();base=ROOT/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full';ref=ROOT/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';out=ref/(f'furniture_r{a.revision}'+('_'+a.tag if a.tag else ''));out.mkdir(exist_ok=True);state=out/'job.json';assert not state.exists();names=a.names.split(',');views=[v for v in json.loads((a.views or residential_canonical_path()).read_text()) if v['name'] in names];assert len(views)==len(names)
for v in views:v.update(render_width=1280,samples=48)
vf=out/'views.json';vf.write_text(json.dumps(views,indent=2));d={'pid':os.getpid(),'phase':'rendering','revision':a.revision,'device':'CPU','started_at':datetime.datetime.now(datetime.timezone.utc).isoformat()};state.write_text(json.dumps(d,indent=2))
try:
 cmd=['python3',str(ROOT/'tools/infinigen/run_bundled_blender.py'),'-t','8','--background',str(base/f'scene_candidate_r{a.revision}.blend'),'--python-exit-code','1','--python',str(Path(__file__).with_name('render.py')),'--','--views',str(vf),'--out',str(out/'candidate'),'--width','1280','--samples','48']
 if a.preserve_source_lighting:cmd.append('--preserve-source-lighting')
 with (out/'render.log').open('w') as f:subprocess.run(cmd,cwd=ROOT,env={**os.environ,'CUDA_VISIBLE_DEVICES':''},stdout=f,stderr=subprocess.STDOUT,check=True)
 d['phase']='rendered_visual_review_pending'
except Exception as e:d.update(phase='failed',error=str(e));raise
finally:d['updated_at']=datetime.datetime.now(datetime.timezone.utc).isoformat();state.write_text(json.dumps(d,indent=2))
