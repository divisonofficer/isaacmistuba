"""Measured 2-D standing-area connectivity, with explicit door-state assumption.

Uses actual projected floor meshes and actual object bounds. It does not claim
dynamic navigation, stair headroom or exhaustive triangle collision validity.
"""
import argparse
from collections import deque
import hashlib
import json
from pathlib import Path
import sys
import bpy
import numpy as np
from mathutils import Vector
from shapely import contains_xy
from shapely.geometry import Polygon,MultiPoint
from shapely.ops import unary_union

ap=argparse.ArgumentParser();ap.add_argument('--blend',type=Path,required=True);ap.add_argument('--reference',type=Path,required=True)
ap.add_argument('--out',type=Path,required=True);ap.add_argument('--radius',type=float,default=.25);ap.add_argument('--step',type=float,default=.10)
a=ap.parse_args(sys.argv[sys.argv.index('--')+1:]);bpy.ops.wm.open_mainfile(filepath=str(a.blend.resolve()))
contract=json.loads((a.reference/'scene_contract.json').read_text());mapping=json.loads((a.reference/'room_mapping.json').read_text())
scene_id=contract['scene_id']
def bounds(o):return [o.matrix_world@Vector(c) for c in o.bound_box]
def footprint(o):return MultiPoint([(v.x,v.y) for v in bounds(o)]).convex_hull
def domain(o):
    polys=[]
    for f in o.data.polygons:
        pts=[o.matrix_world@o.data.vertices[i].co for i in f.vertices]
        n=(pts[1]-pts[0]).cross(pts[2]-pts[0])
        if n.length<1e-8 or abs(n.z)/n.length<.5:continue
        p=Polygon([(v.x,v.y) for v in pts])
        if p.is_valid and p.area>1e-8:polys.append(p)
    assert polys,o.name
    return unary_union(polys)
floors={o.name:domain(o) for o in bpy.data.objects if o.type=='MESH' and o.name.endswith('.floor')}
floor=unary_union(list(floors.values()))
floor_z=min(min(v.z for v in bounds(o)) for o in bpy.data.objects if o.name.endswith('.floor'))
blocking=[];inventory=[]
for o in bpy.data.objects:
    if o.type!='MESH' or o.get('reference_scene_owner')!=scene_id:continue
    kind=o.get('audit_kind','furniture');pts=bounds(o);low=min(v.z for v in pts);high=max(v.z for v in pts)
    if kind in ('furniture','ground_container') or (kind=='fixture' and low<floor_z+1.2 and high>floor_z+.35):
        blocking.append(footprint(o));inventory.append(o.name)
walk=floor.buffer(.012).buffer(-a.radius)
if blocking:walk=walk.difference(unary_union(blocking).buffer(a.radius))
x0,y0,x1,y1=floor.bounds
xs=np.arange(x0+a.step/2,x1,a.step);ys=np.arange(y0+a.step/2,y1,a.step);xx,yy=np.meshgrid(xs,ys)
mask=contains_xy(walk,xx,yy);visited=np.zeros(mask.shape,dtype=bool)
entry=contract.get('entry_room') or mapping['shared_entrance']['room_id']
entrypoly=floors[entry+'.floor'];target=entrypoly.representative_point()
entrymask=mask & contains_xy(entrypoly,xx,yy);candidates=np.argwhere(entrymask)
assert len(candidates),'No standable cell in entrance room'
start=min(candidates,key=lambda ij:(xs[ij[1]]-target.x)**2+(ys[ij[0]]-target.y)**2)
queue=deque([tuple(start)]);visited[tuple(start)]=True
while queue:
    y,x=queue.popleft()
    for dy,dx in ((1,0),(-1,0),(0,1),(0,-1)):
        ny,nx=y+dy,x+dx
        if 0<=ny<len(ys) and 0<=nx<len(xs) and mask[ny,nx] and not visited[ny,nx]:
            visited[ny,nx]=True;queue.append((ny,nx))
rooms=[];failures=[]
for key,row in mapping.items():
    poly=floors[row['room_id']+'.floor'];inside=contains_xy(poly,xx,yy)
    total=int(np.count_nonzero(mask&inside));reachable=int(np.count_nonzero(visited&inside))
    fraction=reachable/total if total else 0
    good=reachable>=4 and fraction>=.5
    rooms.append({'space':key,'room_id':row['room_id'],'free_standing_cells':total,'reachable_cells':reachable,'reachable_fraction':fraction,'pass':good})
    if not good:failures.append(key)
doc={'source':str(a.blend.resolve()),'source_sha256':hashlib.sha256(a.blend.read_bytes()).hexdigest(),'scene_id':scene_id,
     'status':'pass_bounded_connectivity' if not failures else 'needs_route_correction',
     'actor_diameter_m':a.radius*2,'grid_step_m':a.step,'minimum_reachable_fraction':.5,'entry_room':entry,
     'blocked_object_count':len(blocking),'blocked_objects':inventory,'rooms':rooms,'failures':failures,
     'visual_acceptance':False,'limitations':['Assumes operable doors opened; does not certify their current leaf pose',
       '2-D footprint envelope test; does not certify dynamic motion or all mesh intersections',
       'Staircase reachability refers to ground standing area, not upper-flight headroom',
       '0.012m floor union tolerance bridges mesh seams; actor diameter0.50m']}
a.out.write_text(json.dumps(doc,indent=2));print(json.dumps({'status':doc['status'],'failures':failures,'rooms':len(rooms)}))
