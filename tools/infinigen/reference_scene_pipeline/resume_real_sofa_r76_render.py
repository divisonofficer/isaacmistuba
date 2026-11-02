"""Single retry after verified process exit; retain old run and validate all saved-source gates."""
from pathlib import Path
import os,json,hashlib,datetime,subprocess
root=Path(__file__).resolve().parents[3];ref=root/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';state=ref/'real_sofa_r76_render_retry1.json';assert not state.exists();d={'pid':os.getpid(),'phase':'validating_previous_exit_and_saved_source','device':'CPU','photorealism_accepted':False}
def save():d['updated_at']=datetime.datetime.now(datetime.timezone.utc).isoformat();state.write_text(json.dumps(d,indent=2)+'\n');print(json.dumps(d),flush=True)
try:
 save()
 for pid in [1019903,1033268,1033426]:assert not Path(f'/proc/{pid}').exists(),('Prior process still exists; do not duplicate',pid)
 d['previous_attempt']={'driver_exit_code':143,'all_three_recorded_pids_absent':True,'cause':'unknown; no claim of OOM or voluntary cancellation','original_outputs_preserved':True}
 src=root/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full/scene_candidate_r76.blend';digest=hashlib.sha256(src.read_bytes()).hexdigest()
 for stem in ['fine_features','required_spaces_audit','texture_dependencies','functional_assemblies','native_toiletry_assembly_audit','wc_layout_audit']:
  r=json.loads((ref/f'{stem}_r76.json').read_text());assert r['source_sha256']==digest and not r.get('errors'),stem
 d.update(source_sha256=digest,saved_source_gates_verified=6,phase='rendering');save();cmd=['python3',str(Path(__file__).with_name('render_residential_furniture.py')),'--revision','76','--names','101_living,101_sofa_material_close,101_living_media_reverse','--tag','real_sofa_retry1'];subprocess.run(cmd,cwd=root,env={**os.environ,'CUDA_VISIBLE_DEVICES':'','OMP_NUM_THREADS':'4'},check=True);d['phase']='rendered_visual_review_pending'
except Exception as e:d.update(phase='failed',error=str(e));raise
finally:save()
