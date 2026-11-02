"""Actual old/new saved controls plus fresh generated reception family geometry validation."""
import pathlib,subprocess,json,hashlib,sys,os
root=pathlib.Path('/jarvis/project/robomituba');t=pathlib.Path(__file__).parent;ref=root/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';py='/root/miniconda3/envs/infinigen/bin/python';env={**os.environ,'CUDA_VISIBLE_DEVICES':''};controls=[]
for rev,want in [(76,1),(77,0)]:
 out=ref/f'reception_assembly_audit_r{rev}.json';cmd=[py,str(t/'audit_reception_assembly.py'),'--blend',str(root/f'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full/scene_candidate_r{rev}.blend'),'--out',str(out)];p=subprocess.run(cmd,env=env,capture_output=True,text=True);assert p.returncode==want,(rev,p.returncode,p.stdout,p.stderr);controls.append({'revision':rev,'expected_exit':want,'actual_exit':p.returncode,'report':str(out)})
code='''
import sys,json,hashlib,pathlib
root=pathlib.Path('/jarvis/project/robomituba');sys.path.insert(0,str(root/'tools/infinigen'));sys.path.insert(0,str(root/'tools/infinigen/reference_scene_pipeline'))
from room_planner import proc_assets as pa
from audit_reception_assembly import audit_object
pa.VENUE='office';pa.SURFACE_DETAIL=False
rows=[]
for style in [{},{'accent_rgb':(.2,.5,.3)}]:
 pa.STYLE=style
 for length in [2.0,2.4,2.8,3.2]:
  i=len(rows);f=pa.ReceptionDeskFactory(48712502+i);f.L=length;o=f.spawn_asset(i);row=audit_object(o);assert row['pass'],row;rows.append({'length_m':length,'accent':bool(style),'geometry_audit':row})
p=root/'data/venue_refs/floor_plans_v3/native_reception_assembly_validation.json';p.write_text(json.dumps({'factory_file':'tools/infinigen/room_planner/proc_assets.py','factory_sha256':hashlib.sha256((root/'tools/infinigen/room_planner/proc_assets.py').read_bytes()).hexdigest(),'actual_factory_outputs':rows,'scope':'8 actual factory outputs,4 forced supported lengths x2 accent modes;surface detail disabled inRAM forgeometry-only test. Not photographic acceptance orscene regeneration.'},indent=2));print('Fresh native8 controls passed')
'''
p=subprocess.run([py,'-c',code],env=env,capture_output=True,text=True);assert p.returncode==0,(p.stdout,p.stderr);out=root/'data/venue_refs/floor_plans_v3/reception_assembly_gate_validation.json';out.write_text(json.dumps({'controls':controls,'fresh_factory_validation':'native_reception_assembly_validation.json','success':True,'photorealism_accepted':False},indent=2));print('Old76 rejected,new77 passed,and8 fresh native controls passed',flush=True)
