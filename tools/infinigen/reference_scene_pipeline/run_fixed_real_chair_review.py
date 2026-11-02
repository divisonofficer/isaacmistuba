"""Validated exact texture repair then six fixed-camera CPU frames; never scene adoption."""
import json,subprocess,os
from pathlib import Path
root=Path(__file__).resolve().parents[3];t=Path(__file__).parent;p=root/'data/venue_refs/floor_plans_v3/commercial_office_floor_02/real_chair_candidates';state=p/'fixed_review_job.json';assert not state.exists();assert not (p/'review_render_fixed').exists();env={**os.environ,'CUDA_VISIBLE_DEVICES':'','OMP_NUM_THREADS':'4'};d={'pid':os.getpid(),'phase':'validating_saved_texture_bytes','device':'CPU','photorealism_accepted':False}
def save():state.write_text(json.dumps(d,indent=2)+'\n');print(json.dumps(d),flush=True)
try:
 save();subprocess.run(['/root/miniconda3/envs/infinigen/bin/python',str(t/'validate_saved_chair_texture_repair.py')],cwd=root,env=env,check=True);d['phase']='rendering';save();cmd=['python3',str(root/'tools/infinigen/run_bundled_blender.py'),'-t','8','--background',str(p/'review_studio_textures_fixed.blend'),'--python-exit-code','1','--python',str(t/'render.py'),'--','--views',str(p/'review_views.json'),'--out',str(p/'review_render_fixed'),'--width','1280','--samples','64','--preserve-source-lighting'];subprocess.run(cmd,cwd=root,env=env,check=True);d['phase']='rendered_visual_review_pending'
except Exception as e:d.update(phase='failed',error=str(e));raise
finally:save()
