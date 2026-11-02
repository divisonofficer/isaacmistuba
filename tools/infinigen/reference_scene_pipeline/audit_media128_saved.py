"""Reopen native placement: exact mesh, dimensions, evaluated contact rays; bounded checks."""
import bpy,json,sys,hashlib
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree
r=Path(__file__).resolve().parents[3];sys.path.insert(0,str(Path(__file__).parent));from compact_wc_contract import mesh_geometry_hash
from physical_scene_geometry import evaluated_surface
D=r/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';a=json.loads((D/'compact_media128_build.json').read_text());prior=json.loads((D/'compact_media127_build.json').read_text());bpy.ops.wm.open_mainfile(filepath=a['candidate']);bpy.context.view_layer.update();rows=[]
for entry in a['rows']:
 parts=[bpy.data.objects[n] for n in entry['objects']];ps=[o.matrix_world@v.co for o in parts for v in o.data.vertices];lo=Vector([min(p[k] for p in ps) for k in range(3)]);hi=Vector([max(p[k] for p in ps) for k in range(3)]);unit=entry['unit'];kind=entry['kind'];floor=bpy.data.objects['living-room_0/0.floor' if unit==101 else 'living-room_0/1.floor'];fvs,fs,used=evaluated_surface(floor);floor_tree=BVHTree.FromPolygons(fvs,fs,all_triangles=True);contacts=[]
 if kind=='console':
  for o in parts:
   vs,faces,used=evaluated_surface(o)
   for j in used:
    v=vs[j]
    if v.z>lo.z+.001:continue
    hit,n,i,dist=floor_tree.ray_cast(v+Vector((0,0,.02)),Vector((0,0,-1)),.08);contacts.append({'point':list(v),'upward_floor_gap_m':v.z-hit.z if hit is not None and n.z>.8 else None})
 else:
  wall=bpy.data.objects[f'Residential127_{unit}_living_media_privacy_return'];vs,fs,u=evaluated_surface(wall);tree=BVHTree.FromPolygons(vs,fs,all_triangles=True);back=hi.x if unit==101 else lo.x;direction=Vector((1 if unit==101 else -1,0,0))
  for fy in [.15,.5,.85]:
   for fz in [.15,.5,.85]:
    v=Vector((back,lo.y+(hi.y-lo.y)*fy,lo.z+(hi.z-lo.z)*fz));hit,n,i,dist=tree.ray_cast(v,direction,.05);contacts.append({'point':list(v),'back_wall_gap_m':dist if hit is not None else None})
 expected=list(entry['dimensions_xyz_m']);size=list(hi-lo);native=all(mesh_geometry_hash(o.data)==o['native_geometry_sha256'] for o in parts);support=bool(contacts) and all((c.get('upward_floor_gap_m') is not None and abs(c['upward_floor_gap_m'])<.003) if kind=='console' else (c.get('back_wall_gap_m') is not None and c['back_wall_gap_m']<.002) for c in contacts);rows.append({'unit':unit,'kind':kind,'bbox_m':[list(lo),list(hi)],'dimensions_xyz_m':size,'exact_native_mesh':native,'saved_dimensions_match':max(abs(x-y) for x,y in zip(size,expected))<1e-5,'contact_rays':contacts,'bounded_support_pass':support})
result={'source':a['candidate'],'rows':rows,'bounded_pass':all(x['exact_native_mesh'] and x['saved_dimensions_match'] and x['bounded_support_pass'] for x in rows),'accepted':False,'scope':'Exact raw mesh and reopened dimensions, actual lowest evaluated console vertices to native living floor rays; TV bounding rear-plane9 rays to actual evaluated plaster wall. Wall gap is geometric interface only: no mounting hardware/structural load certification, no global collision/navigation/reference/photorealism acceptance.'};(D/'compact_media128_saved_audit.json').write_text(json.dumps(result,indent=2));print('MEDIA128_SAVED',result['bounded_pass'],[(x['unit'],x['kind'],x['dimensions_xyz_m'],x['bounded_support_pass']) for x in rows],flush=True)
