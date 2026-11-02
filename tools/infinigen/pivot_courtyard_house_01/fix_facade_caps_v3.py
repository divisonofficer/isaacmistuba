"""Remove Boolean caps from surface-only architectural envelopes, not solid walls."""
import bpy,bmesh,json
from pathlib import Path
from mathutils import Vector
R=Path(__file__).resolve().parents[3];F=R/'out/infinigen_v2/kr_pivotHouse_48712501/full';B=R/'data/venue_refs/floor_plans_v3/pivot_courtyard_house_01';changes=[]
for prefix,axis,planes,other,span in [('kitchen_0/0',0,[16.245,16.895],1,[4.275,8.725]),('living-room_0/2',1,[3.615,4.265],0,[13.225,16.475])]:
 for suffix in ['.exterior','.wall']:
  o=bpy.data.objects.get(prefix+suffix)
  if not o:continue
  bm=bmesh.new();bm.from_mesh(o.data);inv=o.matrix_world.inverted();faces=[]
  for face in bm.faces:
   c=o.matrix_world@face.calc_center_median();normal=o.matrix_world.to_3x3()@face.normal
   if any(abs(c[axis]-v)<.003 for v in planes) and abs(normal[axis])>.98 and span[0]-.01<c[other]<span[1]+.01 and .13<c.z<2.59:faces.append(face)
  changes.append({'object':o.name,'removed_cut_caps':len(faces)});bmesh.ops.delete(bm,geom=faces,context='FACES');bm.to_mesh(o.data);bm.free()
bpy.context.view_layer.update();bpy.ops.wm.save_as_mainfile(filepath=str(F/'scene_rework_facade_v3.blend'))
(B/'facade_caps_fix_v3.json').write_text(json.dumps({'status':'geometry_fix_visual_review_pending','changes':changes,'cause':'Boolean intersection added closing caps to surface-only exterior envelopes; diagnostic rays hit the cutter end plane instead of kitchen furniture.'},indent=2));print('FACADE_CAPS_V3_SAVED',changes,flush=True)
