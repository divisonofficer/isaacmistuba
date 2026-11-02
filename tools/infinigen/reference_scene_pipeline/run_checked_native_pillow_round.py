"""CPU-only room round gated by reviewed kernel hash andactual saved geometry reports;never promotes."""
import argparse,datetime,hashlib,json,os,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];T=Path(__file__).parent;REF=ROOT/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';BASE=ROOT/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full';p=argparse.ArgumentParser();p.add_argument('--revision',type=int,required=True);p.add_argument('--builder',type=Path,required=True);p.add_argument('--geometry-review',type=Path,default=REF/'pillow_corner_studio/visual_review.json');p.add_argument('--shape-kernel',type=Path,default=T/'pillow_shape_refinement.py');p.add_argument('--validate-only',action='store_true');a=p.parse_args();builder=a.builder.resolve();assert builder.parent==T.resolve() and builder.is_file();review=json.loads(a.geometry_review.read_text());kernel_path=a.shape_kernel.resolve();assert kernel_path.parent==T.resolve() and kernel_path.is_file();kernel=hashlib.sha256(kernel_path.read_bytes()).hexdigest();assert review.get('accepted_for_room_trial') is True and review.get('source_kernel_sha256')==kernel,'geometry review/kernel mismatch'
dependencies=review.get('kernel_dependencies_sha256',{})
for path,expected in dependencies.items():
 dep=Path(path).resolve();assert dep.parent==T.resolve() and dep.is_file();assert hashlib.sha256(dep.read_bytes()).hexdigest()==expected,'geometry dependency mismatch'
rev=a.revision;candidate=BASE/f'scene_candidate_r{rev}.blend'
if a.validate_only:print(json.dumps({'status':'geometry_gate_valid','revision':rev,'builder':str(builder),'no_build_or_render_started':True}));raise SystemExit(0)
state=REF/f'checked_native_pillow_round_r{rev}.json';assert not state.exists();assert not candidate.exists();env={**os.environ,'CUDA_VISIBLE_DEVICES':'','OMP_NUM_THREADS':'8'};d={'pid':os.getpid(),'phase':'building','revision':rev,'device':'CPU','geometry_review':str(a.geometry_review),'reviewed_kernel_sha256':kernel,'reviewed_kernel_dependencies_sha256':dependencies,'children':[],'photorealism_accepted':False,'started_at':datetime.datetime.now(datetime.timezone.utc).isoformat()}
def save(**kw):d.update(kw);state.write_text(json.dumps(d,indent=2));print(json.dumps(kw),flush=True)
try:
 save();subprocess.run(['/root/miniconda3/envs/infinigen/bin/python',str(builder)],cwd=ROOT,env=env,check=True);assert candidate.exists();meta=json.loads((REF/f'realism_refinement_r{rev}.json').read_text());assert Path(meta['candidate'])==candidate and meta.get('shape_kernel_sha256')==kernel;save(phase='saved_geometry_preflight')
 for path,expected in dependencies.items():assert hashlib.sha256(Path(path).read_bytes()).hexdigest()==expected,'dependency changed during build'
 subprocess.run(['/root/miniconda3/envs/infinigen/bin/python',str(T/'audit_native_bed_pillows.py'),'--blend',str(candidate),'--out',str(REF/f'native_bed_pillows_audit_r{rev}.json')],cwd=ROOT,env=env,check=True)
 subprocess.run(['python3',str(T/'run_current_fine_audits.py'),'--scene','residential','--revision',str(rev)],cwd=ROOT,env=env,check=True)
 for name in ['native_bed_pillows_audit','fine_features','required_spaces_audit','texture_dependencies']:
  report=json.loads((REF/f'{name}_r{rev}.json').read_text());assert not report.get('errors'),(name,report.get('errors'))
 save(phase='rendering',saved_geometry_reports_passed=True)
 children=[];views=BASE/'review_views_fine_r45.json';side=REF/'pillow_threequarter_views_r53.json'
 for tag,name,vf in [('bed_smooth','101_bedroom2',views),('bed_smooth_reverse','102_bedroom2_reverse',views),('pillow_angle_smooth','101_pillow_threequarter',side)]:
  cmd=['python3',str(T/'render_residential_furniture.py'),'--revision',str(rev),'--names',name,'--views',str(vf),'--tag',tag];child=subprocess.Popen(cmd,cwd=ROOT,env=env);children.append(child);d['children'].append({'pid':child.pid,'tag':tag,'view':name});save()
 codes=[c.wait() for c in children];assert all(code==0 for code in codes),codes;save(phase='rendered_visual_review_pending',render_exit_codes=codes)
except Exception as e:save(phase='failed',error=str(e));raise
