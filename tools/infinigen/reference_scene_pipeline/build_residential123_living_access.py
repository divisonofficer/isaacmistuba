"""Rigidly relocate two actual native media walls that obstruct the living portals."""
import bpy,json,hashlib,sys,math
from pathlib import Path
from mathutils import Vector,Matrix
from mathutils.bvhtree import BVHTree
r=Path(__file__).resolve().parents[3];sys.path.insert(0,str(Path(__file__).parent));from compact_wc_contract import mesh_geometry_hash
from physical_scene_geometry import render_mesh_candidates,evaluated_surface
base=r/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full';d=r/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';src=base/'scene_candidate_r122_draft.blend';dst=base/'scene_candidate_r123_draft.blend';assert not dst.exists();sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();before_sha=sha(src);bpy.ops.wm.open_mainfile(filepath=str(src));before_matrices={o.name:[list(v) for v in o.matrix_world] for o in bpy.context.scene.objects};objects,inventory=render_mesh_candidates();fz=.1145347;rows=[];changed=set()
def bbox(o):
 p=[o.matrix_world@v.co for v in o.data.vertices];return Vector([min(v[k] for v in p) for k in range(3)]),Vector([max(v[k] for v in p) for k in range(3)])
for unit in [101,102]:
 o=next(o for o in bpy.context.scene.objects if o.get('program_key')==f'{unit}_living_media');family=[o]+list(o.children_recursive);old={p:p.matrix_world.copy() for p in family};lo,hi=bbox(o);centre=(lo+hi)/2;turn=Matrix.Translation(centre)@Matrix.Rotation((-1 if unit==101 else 1)*math.pi/2,4,'Z')@Matrix.Translation(-centre);native_hash=mesh_geometry_hash(o.data)
 for p in family:p.matrix_world=turn@old[p]
 bpy.context.view_layer.update();a,b=bbox(o);target_x=1.55 if unit==101 else 19.95;delta=Vector((target_x-(a.x+b.x)/2,6.12-a.y,0));move=Matrix.Translation(delta)
 for p in family:p.matrix_world=move@p.matrix_world;changed.add(p.name)
 bpy.context.view_layer.update();a,b=bbox(o);assert mesh_geometry_hash(o.data)==native_hash;ps,fs,used=evaluated_surface(o);tree=BVHTree.FromPolygons(ps,fs,all_triangles=True);collisions=[]
 for other in objects:
  if other in family:continue
  q=[other.matrix_world@Vector(v) for v in other.bound_box];qlo=Vector([min(v[k] for v in q) for k in range(3)]);qhi=Vector([max(v[k] for v in q) for k in range(3)])
  if any(qhi[k]<a[k] or qlo[k]>b[k] for k in range(3)) or qhi.z<fz+.02:continue
  pp,ff,uu=evaluated_surface(other);ot=BVHTree.FromPolygons(pp,ff,all_triangles=True);hits=tree.overlap(ot)
  if hits:collisions.append({'object':other.name,'surface_crossings':len(hits)})
 rows.append({'unit':unit,'object':o.name,'family':[p.name for p in family],'before_bbox_m':[list(lo),list(hi)],'after_bbox_m':[list(a),list(b)],'rigid_rotation_z_deg':-90 if unit==101 else 90,'translation_after_rotation_m':list(delta),'native_geometry_sha256_unchanged':native_hash,'native_object_scale':list(o.scale),'floor_gap_m':a.z-fz,'surface_intersections':collisions,'scope':'Native entire media-wall assembly moved to south wall, no mesh simplification/rescale/material or lighting edits. Surface-only intersection preflight is not containment/support/route or reference-composition approval.'})
assert all([list(v) for v in o.matrix_world]==before_matrices[o.name] for o in bpy.context.scene.objects if o.name not in changed);bpy.ops.wm.save_as_mainfile(filepath=str(dst));assert sha(src)==before_sha;(d/'living123_media_relocation_build.json').write_text(json.dumps({'source':str(src),'source_sha256':before_sha,'candidate':str(dst),'candidate_sha256':sha(dst),'rows':rows,'unrelated_object_matrices_unchanged':True,'reason':'Actual600mm centered portal routes in122 intersect only native living media walls,181 surface crossings each. Relocate actual products instead of shrinking them or deleting physical obstacles from navigation tests.','accepted':False,'scope':'Unapproved layout candidate; physical route/full-floor screen and matched living/reference camera composition required. Reference arrangement tradeoff must be reported.'},indent=2));print('RESIDENTIAL123_MEDIA_RELOCATION_SAVED',[(x['unit'],x['after_bbox_m'],x['surface_intersections']) for x in rows])
