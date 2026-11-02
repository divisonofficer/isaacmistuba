import pathlib,subprocess,os,json
root=pathlib.Path(__file__).resolve().parents[3];t=pathlib.Path(__file__).parent;ref=root/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';state=ref/'private_chair84_wall_material_control_job.json';assert not state.exists();env={**os.environ,'CUDA_VISIBLE_DEVICES':'','OMP_NUM_THREADS':'4'};d={'pid':os.getpid(),'phase':'building','device':'CPU','photorealism_accepted':False,'diagnostic_only':True}
def save():state.write_text(json.dumps(d,indent=2)+'\n');print(json.dumps(d),flush=True)
try:
 save();subprocess.run(['/root/miniconda3/envs/infinigen/bin/python',str(t/'build_private_wall_material_control_r84.py')],cwd=root,env=env,check=True);p=ref/'private_chair84_wall_material_control';d['phase']='rendering';save();subprocess.run(['python3',str(root/'tools/infinigen/run_bundled_blender.py'),'-t','8','--background',str(p/'source.blend'),'--python-exit-code','1','--python',str(t/'render.py'),'--','--views',str(p/'views.json'),'--out',str(p/'candidate'),'--width','1280','--samples','48'],cwd=root,env=env,check=True);d['phase']='rendered_visual_review_pending'
except Exception as e:d.update(phase='failed',error=str(e));raise
finally:save()
