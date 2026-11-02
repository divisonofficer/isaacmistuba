"""Saved-source checks for ten actual products and two new room assemblies.
Not a full ten-room navigation gate or visual acceptance.
"""
import bpy
import hashlib
import json
import sys
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from shapely.geometry import MultiPoint, LineString
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(Path(__file__).parent))
from wc_layout_checks import evaluated_geometry, bounds, seat_measurement
from compact_wc_contract import mesh_geometry_hash
D=ROOT/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03/core_wc104_planning'
contract=json.loads((D.parent/'native_fullsize_wc100/contract.json').read_text())
build=json.loads((D/'draft_build.json').read_text());source=Path(build['draft'])
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
assert sha(source)==build['draft_sha256']
bpy.ops.wm.open_mainfile(filepath=str(source))

def geometry(obj):
 ev,mesh,points=evaluated_geometry(obj)
 faces=[tuple(f.vertices) for f in mesh.polygons]
 ev.to_mesh_clear()
 return points,faces

def bvh(obj):
 points,faces=geometry(obj)
 return BVHTree.FromPolygons(points,faces,all_triangles=False)

errors=[];toilets=[]
for obj in bpy.context.scene.objects:
 if obj.type!='MESH' or not str(obj.get('program_key','')).endswith('_wc'):continue
 lo,hi=bounds(obj);size=hi-lo;seat=seat_measurement(obj)
 row={'key':obj['program_key'],'object':obj.name,'bbox_m':[list(lo),list(hi)],'dimensions_xyz_m':list(size),'seat_height_m':seat['seat_height_m'],'scale':list(obj.scale),'native_mesh_identical':mesh_geometry_hash(obj.data)==contract['mesh_geometry_sha256']}
 row['pass']=row['native_mesh_identical'] and max(abs(v-1) for v in obj.scale)<1e-6 and .400<=seat['seat_height_m']<=.420
 if not row['pass']:errors.append(row['key']+':native product/seat fail')
 toilets.append(row)
assert len(toilets)==10
architecture=[o for o in bpy.context.scene.objects if o.type=='MESH' and (o.name.endswith(('.wall','.exterior')) or o.name.startswith('Core104_'))]
cache={};new_assemblies=[]
for unit in (101,102):
 candidates=[o for o in bpy.context.scene.objects if o.type=='MESH' and str(o.get('program_key','')).startswith(f'{unit}_core_wc')]
 collisions=[];items=[]
 for obj in candidates:
  lo,hi=bounds(obj);tree=bvh(obj)
  for wall in architecture:
   a,b=bounds(wall)
   if any(hi[k]<a[k]-1e-6 or lo[k]>b[k]+1e-6 for k in range(3)):continue
   if wall.name not in cache:cache[wall.name]=bvh(wall)
   hits=tree.overlap(cache[wall.name])
   if hits:collisions.append({'object':obj.name,'wall':wall.name,'surface_triangle_intersections':len(hits)})
  items.append({'object':obj.name,'key':obj['program_key'],'bbox_m':[list(lo),list(hi)]})
 door=next(o for o in candidates if o['program_key'].endswith('_door'))
 # Actual open leaf/handles, excluding fixed frame by its native material slot.
 ids={i for f in door.data.polygons if door.data.materials[f.material_index].name.split('.')[0]!='office02_charcoal' for i in f.vertices}
 hull=MultiPoint([(door.matrix_world@door.data.vertices[i].co).xy[:] for i in ids]).convex_hull
 points=[(9.4,6.8),(7.45,6.8),(7.45,8.25),(8.45,8.25),(8.45,8.365)]
 if unit==102:points=[(21.5-x,y) for x,y in points]
 route=LineString(points).buffer(.3,resolution=32)
 open_leaf_route_area=route.intersection(hull).area
 if collisions:errors.append(str(unit)+':new fixtures/door intersect architectural surfaces')
 if open_leaf_route_area>1e-9:errors.append(str(unit)+':fully open native leaf blocks proposed600mm route')
 new_assemblies.append({'unit':unit,'objects':items,'architectural_surface_collisions':collisions,'actual_open_leaf_route_overlap_m2':open_leaf_route_area,'scope':'New fixtures/native door versus wall triangles;actual fully-open leaf versus proposed2D600mm route. Not continuous sweep nor entire ten-room navigation.'})
assert sha(source)==build['draft_sha256']
report={'source':str(source),'source_sha256':sha(source),'native_toilets':toilets,'new_assemblies':new_assemblies,'errors':errors,'bounded_checks_pass':not errors,'photorealism_accepted':False,'dataset_promoted':False,'full_ten_room_access_gate_complete':False,'remaining':['Continuous native door sweeps and real casing-inclusive route rays','All ten bathroom navigation and unchanged old8source regression','Room tags/finishes/plumbing/mountings and actual RGB review']}
(D/'draft_saved_audit.json').write_text(json.dumps(report,indent=2)+'\n')
print('CORE104_SAVED_AUDIT','PASS' if not errors else 'HOLD',json.dumps(errors),flush=True)
