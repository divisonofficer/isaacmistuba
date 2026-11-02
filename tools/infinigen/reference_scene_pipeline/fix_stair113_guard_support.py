"""Move stair guard lines onto actual concrete; inspect raw post support rays."""
import bpy,json,hashlib
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree
r=Path(__file__).resolve().parents[3];d=r/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';b=r/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full';src=b/'scene_candidate_r112_draft.blend';dst=b/'scene_candidate_r113_draft.blend';assert not dst.exists();bpy.ops.wm.open_mainfile(filepath=str(src));moves=[]
for o in bpy.context.scene.objects:
 if o.type!='MESH' or o.get('audit_kind')!='stair_guard':continue
 key=str(o.get('program_key',''));pts=[o.matrix_world@v.co for v in o.data.vertices];cx=(min(v.x for v in pts)+max(v.x for v in pts))/2
 # Whole horizontal landing rail must shorten with its end posts; internal posts retain positions.
 if 'landing_guard' in o.name and max(v.x for v in pts)-min(v.x for v in pts)>2:
  inv=o.matrix_world.inverted()
  for v in o.data.vertices:
   q=o.matrix_world@v.co;q.x=10.75+(q.x-10.75)*(2.7/2.9);v.co=inv@q
  moves.append({'object':o.name,'change':'landing rail endpoints shortened to supported guard lines'});continue
 dx=next((shift for x,shift in [(9.3,.1),(10.5,-.1),(11.0,.1),(12.2,-.1)] if abs(cx-x)<.03),0)
 if dx:o.location.x+=dx;moves.append({'object':o.name,'dx_m':dx})
bpy.context.view_layer.update();verts=[];faces=[]
for o in bpy.context.scene.objects:
 if o.get('audit_kind')!='stair_structure':continue
 base=len(verts);verts.extend(o.matrix_world@v.co for v in o.data.vertices);faces.extend(tuple(base+i for i in f.vertices) for f in o.data.polygons)
t=BVHTree.FromPolygons(verts,faces);checks=[]
for o in bpy.context.scene.objects:
 if o.type!='MESH' or o.get('audit_kind')!='stair_guard' or 'post' not in o.name.lower():continue
 ps=[o.matrix_world@v.co for v in o.data.vertices];lo=min(v.z for v in ps);low=[v for v in ps if v.z<lo+.0001];gaps=[]
 for q in low:
  hit=t.ray_cast(q+Vector((0,0,.02)),Vector((0,0,-1)),.12)[0]
  if hit:gaps.append(q.z-hit.z)
 checks.append({'object':o.name,'low_samples':len(low),'supported_samples':len(gaps),'min_gap_m':min(gaps) if gaps else None,'max_gap_m':max(gaps) if gaps else None,'pass':len(gaps)==len(low) and min(gaps)>=-.003 and max(gaps)<.003})
assert checks and all(x['pass'] for x in checks),checks
bpy.ops.wm.save_as_mainfile(filepath=str(dst));(d/'stair113_guard_support.json').write_text(json.dumps({'source':str(src),'source_sha256':hashlib.sha256(src.read_bytes()).hexdigest(),'candidate':str(dst),'candidate_sha256':hashlib.sha256(dst.read_bytes()).hexdigest(),'moves':moves,'post_support_checks':checks,'pass':True,'scope':'Guard posts moved100mm inward to actual concrete and low vertex ray support checked. Landing rail shortened. No base plates/anchors, full guard load/gap certification, navigation or visual acceptance.'},indent=2));print('STAIR113_GUARD_SUPPORT_PASS')
