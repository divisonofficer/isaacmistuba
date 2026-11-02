"""Remove nonresidential clinic props revealed by reverse camera; correct rejected BED04 camera."""
import bpy,json
from pathlib import Path
R=Path(__file__).resolve().parents[3];B=R/'data/venue_refs/floor_plans_v3/pivot_courtyard_house_01';F=R/'out/infinigen_v2/kr_pivotHouse_48712501/full';removed=[]
for o in list(bpy.data.objects):
 if o.parent is None and 'ClinicWallItemFactory' in o.name and str(o.get('ir_room','')).startswith(('hallway','living-room','bedroom','office','closet')):
  removed.append({'name':o.name,'room':o.get('ir_room'),'materials':[m.name if m else None for m in o.data.materials] if o.type=='MESH' else []})
  for c in reversed(list(o.children_recursive)):bpy.data.objects.remove(c,do_unlink=True)
  bpy.data.objects.remove(o,do_unlink=True)
v=json.loads((F/'review_views_r17.json').read_text())
for q in v:
 if q['name']=='bed4_reverse':q.update(location=[2.0,17.50,1.65],target=[.85,19.5,1.10],hfov=85)
(F/'review_views_r19.json').write_text(json.dumps(v,indent=2)+'\n')
bpy.context.scene['pivot_revision']='r19_residential_props';bpy.ops.wm.save_as_mainfile(filepath=str(F/'scene_review_r19.blend'))
(B/'revision_r19.json').write_text(json.dumps({'removed_nonresidential_clinic_props':removed,'camera_corrected':'bed4_reverse','architecture_changed':False},indent=2));print('PIVOT_R19_COMPLETE',flush=True)
