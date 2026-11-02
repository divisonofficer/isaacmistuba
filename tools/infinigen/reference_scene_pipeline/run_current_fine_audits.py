"""Read-only exact-source preflights; individual reports retain their bounded scopes."""
import argparse,json,os,subprocess,datetime
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];p=argparse.ArgumentParser();p.add_argument('--scene',choices=['office','residential'],required=True);p.add_argument('--revision',type=int);a=p.parse_args();office=a.scene=='office';scene='commercial_office_floor_02' if office else 'dual_unit_residential_floor_03';seed=48712502 if office else 48712503;rev=a.revision if a.revision is not None else (43 if office else 47);ref=ROOT/'data/venue_refs/floor_plans_v3'/scene;base=ROOT/'out/infinigen_v2'/f'kr_{scene}_{seed}'/'full';src=base/f'scene_candidate_r{rev}.blend';views=base/('review_views_delivery_r23.json' if office else 'review_views_fine_r45.json');t=Path(__file__).parent;python='/root/miniconda3/envs/infinigen/bin/python';jobs=[]
if office:
 jobs.append([python,str(t/'audit_geometry.py'),'--','--blend',str(src),'--scene',scene,'--out',str(ref/f'geometry_audit_r{rev}.json')])
 jobs.append([python,str(t/'audit_saved_wall_overlap.py'),'--blend',str(src),'--out',str(ref/f'wall_overlap_audit_r{rev}.json')])
else:jobs.append([python,str(t/'audit_fine_features.py'),'--blend',str(src),'--out',str(ref/f'fine_features_r{rev}.json')])
jobs.append([python,str(t/'audit_required_spaces.py'),'--blend',str(src),'--reference',str(ref),'--views',str(views),'--out',str(ref/f'required_spaces_audit_r{rev}.json')])
jobs.append([python,str(t/'audit_texture_dependencies.py'),'--blend',str(src),'--out',str(ref/f'texture_dependencies_r{rev}.json')])
jobs.append([python,str(t/'audit_functional_assemblies.py'),'--blend',str(src),'--out',str(ref/f'functional_assemblies_r{rev}.json')])
if office:jobs.append([python,str(t/'audit_reception_assembly.py'),'--blend',str(src),'--out',str(ref/f'reception_assembly_audit_r{rev}.json')])
else:jobs.append([python,str(t/'audit_native_toiletries.py'),'--blend',str(src),'--out',str(ref/f'native_toiletry_assembly_audit_r{rev}.json')])
if not office:jobs.append([python,str(t/'audit_wc_layout.py'),'--blend',str(src),'--out',str(ref/f'wc_layout_audit_r{rev}.json')])
state=ref/f'current_preflight_job_r{rev}.json';assert not state.exists();d={'pid':os.getpid(),'phase':'running','source':str(src),'completed_commands':0,'note':'Process completion is not audit/visual acceptance;read individual reports.'};state.write_text(json.dumps(d,indent=2))
try:
 for command in jobs:subprocess.run(command,cwd=ROOT,env={**os.environ,'CUDA_VISIBLE_DEVICES':''},check=True);d['completed_commands']+=1;state.write_text(json.dumps(d,indent=2))
 d['phase']='reports_written_review_pending'
except Exception as e:d.update(phase='failed',error=str(e));raise
finally:d['updated_at']=datetime.datetime.now(datetime.timezone.utc).isoformat();state.write_text(json.dumps(d,indent=2))
