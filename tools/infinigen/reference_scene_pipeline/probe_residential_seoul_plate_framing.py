"""Three actual same-camera low-res projection controls; no source mutation."""
import bpy,json,sys,runpy
from pathlib import Path
R=Path(__file__).resolve().parents[3];D=R/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';S=R/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full/scene_candidate_r82.blend';OUT=D/'seoul_plate_r82_projection_probe';assert not OUT.exists();OUT.mkdir();bpy.ops.wm.open_mainfile(filepath=str(S));photo=bpy.data.objects['Res03_r82_west_Seoul_photographic_backdrop'];original=[v.co.copy() for v in photo.data.vertices];camera=json.loads((D/'furniture_r82_seoul_plate/candidate/render_receipt.json').read_text())['frames'][0]['camera'];cases=[{'name':'original_72x54_center_z0','scale':1.,'center_z':0.},{'name':'half_36x27_center_z4','scale':.5,'center_z':4.},{'name':'two_thirds_48x36_center_z5','scale':2/3,'center_z':5.}];views=[dict(camera,name=c['name'],render_width=480,samples=16) for c in cases];vf=OUT/'views.json';vf.write_text(json.dumps(views,indent=2)+'\n');counter=[0]
def prepare(scene,*args):
 i=counter[0];assert i<len(cases);case=cases[i]
 for v,p in zip(photo.data.vertices,original):v.co=(p.x,8+(p.y-8)*case['scale'],case['center_z']+p.z*case['scale'])
 photo.data.update();counter[0]+=1
bpy.app.handlers.render_pre.append(prepare)
(OUT/'diagnostic_overrides.json').write_text(json.dumps({'source':str(S),'source_revision':82,'cases':cases,'changes':'Only photographic plate horizontal/vertical extents and center height; x=-45m fixed. Photo/UV/material,room/world/light/exposure and camera unchanged.','samples':16,'width':480,'scope':'Low-res projection screening,not production material/photo/nav acceptance or all-window solution.'},indent=2)+'\n')
sys.argv=['render.py','--','--views',str(vf),'--out',str(OUT/'candidate'),'--width','480','--samples','16'];runpy.run_path(str(Path(__file__).with_name('render.py')),run_name='__main__');assert counter[0]==3;print('SEOUL_PROJECTION_PROBE_COMPLETE',flush=True)
