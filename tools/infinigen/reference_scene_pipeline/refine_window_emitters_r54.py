"""Place three misplaced window proxy emitters at their actual glazing bounds."""
import bpy,json,hashlib
from pathlib import Path
from mathutils import Vector,Matrix
ROOT=Path(__file__).resolve().parents[3]
base=ROOT/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full'
ref=ROOT/'data/venue_refs/floor_plans_v3/commercial_office_floor_02'
src=base/'scene_candidate_r53.blend';out=base/'scene_candidate_r54.blend'
assert not out.exists();sha=hashlib.sha256(src.read_bytes()).hexdigest()
bpy.ops.wm.open_mainfile(filepath=str(src));bpy.context.view_layer.update();rows=[]
for light in list(bpy.data.objects):
 if light.type!='LIGHT' or not light.parent or 'Window' not in light.parent.name:continue
 window=light.parent
 pts=[window.matrix_world@Vector(c) for c in window.bound_box]
 lo=Vector([min(v[i] for v in pts) for i in range(3)]);hi=Vector([max(v[i] for v in pts) for i in range(3)])
 if hi.x<=10 or lo.y>=8:continue
 before={'location':list(light.matrix_world.translation),'direction':list(light.matrix_world.to_3x3()@Vector((0,0,-1))),'energy':light.data.energy}
 center=(lo+hi)/2;extent=hi-lo
 if extent.y<extent.x:
  direction=Vector((0,1,0));width=extent.x*.80
 else:direction=Vector((-1,0,0));width=extent.y*.80
 center+=direction*.22
 light.data=light.data.copy();light.data.shape='RECTANGLE';light.data.size=width;light.data.size_y=extent.z*.80
 light.data.energy=65*width*light.data.size_y
 light.matrix_world=Matrix.Translation(center)@direction.to_track_quat('-Z','Y').to_matrix().to_4x4()
 light['window_proxy_placement_revision']=54
 rows.append({'object':light.name,'window':window.name,'before':before,'after_location':list(center),'after_direction':list(direction),'size':[width,light.data.size_y],'energy':light.data.energy,'glazing_bounds':[list(lo),list(hi)]})
assert len(rows)==3,rows
bpy.context.view_layer.update()
for row in rows:
 actual=bpy.data.objects[row['object']].matrix_world.translation
 assert (actual-Vector(row['after_location'])).length<1e-5
bpy.ops.wm.save_as_mainfile(filepath=str(out));assert hashlib.sha256(src.read_bytes()).hexdigest()==sha
(ref/'realism_refinement_r54.json').write_text(json.dumps({'source':str(src),'source_sha256':sha,'candidate':str(out),'scope':'Only three window proxy light transforms, shapes and area-scaled power; all meshes/materials/ceiling/world/exposure unchanged','changes':rows,'power_policy':'65 W per square metre, matches legacy render window override','photorealism_accepted':False,'requires':'Same-camera wide RGB: inspect blown highlights, material separation, direction and shadow regressions; whole-scene review remains required'},indent=2))
print('SAVED',out,flush=True)
