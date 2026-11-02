"""Resolve the north-wall trial's actual ficus collision by rigid native plant placement."""
import bpy,json,sys,hashlib
from pathlib import Path
from mathutils import Vector,Matrix
from mathutils.bvhtree import BVHTree
r=Path(__file__).resolve().parents[3];sys.path.insert(0,str(Path(__file__).parent));from physical_scene_geometry import render_mesh_candidates,evaluated_surface
from compact_wc_contract import mesh_geometry_hash
base=r/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full';d=r/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';src=base/'scene_candidate_r124_draft.blend';dst=base/'scene_candidate_r125_draft.blend';assert not dst.exists();sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();source_sha=sha(src);bpy.ops.wm.open_mainfile(filepath=str(src));o=bpy.data.objects['Residential03_r89_native_ficus_101_living'];matrix=o.matrix_world.copy();native=mesh_geometry_hash(o.data);oldmatrices={p.name:[list(v) for v in p.matrix_world] for p in bpy.context.scene.objects};original=[matrix@v.co for v in o.data.vertices];lo=Vector([min(p[k] for p in original) for k in range(3)]);hi=Vector([max(p[k] for p in original) for k in range(3)]);cx=(lo.x+hi.x)/2;cy=(lo.y+hi.y)/2;physical,_=render_mesh_candidates();cache={};attempts=[];chosen=None
for tx,ty in [(5.8,8.2),(5.8,8.4),(5.6,8.2),(5.6,8.5),(4.5,6.8)]:
 delta=Vector((tx-cx,ty-cy,0));ps=[p+delta for p in original];a=lo+delta;b=hi+delta
 if a.x<.13 or b.x>6.85 or a.y<6.13 or b.y>9.35:continue
 o.matrix_world=Matrix.Translation(delta)@matrix;bpy.context.view_layer.update();pp,ff,uu=evaluated_surface(o);tree=BVHTree.FromPolygons(pp,ff,all_triangles=True);collisions=[]
 for other in physical:
  if other==o:continue
  q=[other.matrix_world@Vector(v) for v in other.bound_box];qlo=Vector([min(v[k] for v in q) for k in range(3)]);qhi=Vector([max(v[k] for v in q) for k in range(3)])
  if any(qhi[k]<a[k] or qlo[k]>b[k] for k in range(3)) or qhi.z<lo.z+.02:continue
  if other.name not in cache:
   p,f,u=evaluated_surface(other);cache[other.name]=BVHTree.FromPolygons(p,f,all_triangles=True)
  overlaps=tree.overlap(cache[other.name])
  if overlaps:collisions.append({'object':other.name,'surface_crossings':len(overlaps)})
 row={'target_xy_m':[tx,ty],'translation_m':list(delta),'bbox_m':[list(a),list(b)],'surface_collisions':collisions};attempts.append(row)
 if not collisions:chosen=row;break
assert chosen,attempts;assert mesh_geometry_hash(o.data)==native;assert all([list(v) for v in p.matrix_world]==oldmatrices[p.name] for p in bpy.context.scene.objects if p!=o);bpy.ops.wm.save_as_mainfile(filepath=str(dst));assert sha(src)==source_sha;(d/'living125_access_build.json').write_text(json.dumps({'source':str(src),'source_sha256':source_sha,'candidate':str(dst),'candidate_sha256':sha(dst),'plant':o.name,'native_geometry_sha256_unchanged':native,'native_faces':len(o.data.polygons),'scale_unchanged':list(o.scale),'floor_z_unchanged':lo.z,'other_object_matrices_unchanged':True,'attempts':attempts,'chosen':chosen,'accepted':False,'scope':'Only native97348-face ficus+basket translated; media walls remain124 north-wall placements. All enabled render-mesh evaluated surface intersections checked for the new plant envelope. This is not volume-containment, full circulation, reference-fidelity or photorealism certification. Saved support, portal routes, full-floor raster and matched room RGB remain required.'},indent=2));print('RESIDENTIAL125_NATIVE_FICUS_RELOCATED',chosen)
