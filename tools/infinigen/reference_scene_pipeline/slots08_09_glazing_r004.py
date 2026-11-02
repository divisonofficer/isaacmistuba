"""Correct separately saved native room.exterior opaque perimeter behind full glass."""
import bpy,bmesh,json,os,traceback
from pathlib import Path
R=Path(__file__).resolve().parents[3];D=R/'data/venue_refs/floor_plans_v3/skyline_penthouse_08';B=R/'out/infinigen_v2/kr_skyline_penthouse_08_48712508/full';src=B/'scene_candidate_r003.blend';out=B/'scene_candidate_r004.blend';assert not out.exists();jp=D/'build_r004_job.json';job={'pid':os.getpid(),'phase':'correcting_native_exterior_perimeter','source':str(src),'device':'CPU'};jp.write_text(json.dumps(job,indent=2))
try:
 bpy.ops.wm.open_mainfile(filepath=str(src));changed=[]
 for o in bpy.context.scene.objects:
  if o.type!='MESH' or not o.name.endswith(('.exterior','.wall')):continue
  bm=bmesh.new();bm.from_mesh(o.data);faces=[f for f in bm.faces if all((o.matrix_world@v.co).y<.4 for v in f.verts) or all((o.matrix_world@v.co).y>13.6 for v in f.verts)]
  if faces:bmesh.ops.delete(bm,geom=faces,context='FACES');bm.to_mesh(o.data);changed.append({'object':o.name,'removed_north_south_perimeter_faces':len(faces)})
  bm.free()
 bpy.context.view_layer.update();bpy.ops.wm.save_as_mainfile(filepath=str(out));(D/'views_r004.json').write_text((D/'views_r003.json').read_text());(D/'native_exterior_glazing_correction_r004.json').write_text(json.dumps({'source':str(src),'candidate':str(out),'actual_mesh_corrections':changed,'visual_acceptance':False,'scope':'Only north/south outside opaque perimeterfaces removed; native internal architecture retained. Full source-matched image review pending.'},indent=2));job.update(phase='saved_render_pending',candidate=str(out),exit_code=0)
except BaseException as e:job.update(phase='failed',error=repr(e),traceback=traceback.format_exc(),exit_code=1);raise
finally:jp.write_text(json.dumps(job,indent=2));print(job,flush=True)
