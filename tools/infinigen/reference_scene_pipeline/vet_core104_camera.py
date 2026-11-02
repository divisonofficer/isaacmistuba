"""Reject WC inspection views hidden by the actual door before Cycles rendering.
Evaluate bowl/base/upper groups separately so dense bowl topology cannot hide a
missing tank. This is camera coverage only, never bathroom access acceptance.
"""
import bpy,hashlib,json,math
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree
R=Path(__file__).resolve().parents[3];D=R/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03/core_wc104_planning';build=json.loads((D/'draft_build.json').read_text());S=Path(build['draft']);sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();assert sha(S)==build['draft_sha256'];bpy.ops.wm.open_mainfile(filepath=str(S))
def world(o):return o.matrix_basis.copy() if o.parent is None else world(o.parent)@o.matrix_parent_inverse@o.matrix_basis
results=[];selected=[]
for unit in (101,102):
 wc=next(o for o in bpy.context.scene.objects if o.get('program_key')==f'{unit}_core_wc_wc');points=[world(wc)@v.co for v in wc.data.vertices];floor=min(p.z for p in points);groups={'base':[p for p in points if p.z<floor+.25],'bowl':[p for p in points if floor+.25<=p.z<floor+.55],'upper':[p for p in points if p.z>=floor+.55]};vertices=[];faces=[]
 obstacles=[o for o in bpy.context.scene.objects if o.type=='MESH' and (o.name.endswith(('.wall','.exterior')) or o.name.startswith('Core104_') or o.get('program_key')==f'{unit}_core_wc_door')]
 for o in obstacles:
  offset=len(vertices);matrix=world(o);vertices.extend(matrix@v.co for v in o.data.vertices);faces.extend(tuple(offset+i for i in f.vertices) for f in o.data.polygons)
 tree=BVHTree.FromPolygons(vertices,faces)
 def mirror(x):return 21.5-x if unit==102 else x
 trials=[{'name':f'{unit}_old_occluded_control','location':[mirror(7.2),8,1.5],'target':[mirror(8.45),8.9,1.05],'hfov':95},
         {'name':f'{unit}_core_wc_vetted_diagnostic','location':[mirror(8.45),8.25,1.5],'target':[mirror(8.45),9.1,.65],'hfov':90}]
 for trial in trials:
  camera=Vector(trial['location']);forward=(Vector(trial['target'])-camera).normalized();right=forward.cross(Vector((0,0,1))).normalized();up=right.cross(forward).normalized();horizontal=math.tan(math.radians(trial['hfov'])/2);vertical=horizontal*.75;rows=[]
  for name,cloud in groups.items():
   samples=cloud[::max(1,len(cloud)//200)];inside=clear=0
   for point in samples:
    delta=point-camera;depth=delta.dot(forward);frustum=depth>0 and abs(delta.dot(right)/depth)<horizontal and abs(delta.dot(up)/depth)<vertical
    inside+=int(frustum)
    hit,normal,face,distance=tree.ray_cast(camera,delta.normalized(),max(0,delta.length-.002))
    clear+=int(frustum and hit is None)
   rows.append({'group':name,'samples':len(samples),'within_frame_fraction':inside/len(samples),'unblocked_within_frame_fraction':clear/len(samples)})
  passed=all(row['unblocked_within_frame_fraction']>=.95 for row in rows);results.append({'view':trial,'groups':rows,'camera_coverage_pass':passed})
  if 'vetted' in trial['name'] and passed:selected.append(dict(trial,render_width=1280,samples=48))
assert sha(S)==build['draft_sha256'];report={'source':str(S),'source_sha256':sha(S),'results':results,'selected_view_count':len(selected),'scope':'Static source WC vertices against actual wall/new native door triangles and perspective frustum;separate base/bowl/upper groups. Proposed selected camera lies on previously planned600mm centreline. Does not certify actual ten-room navigation,fixture plumbing,materials or photorealism.'};(D/'camera_coverage_audit.json').write_text(json.dumps(report,indent=2)+'\n');(D/'visibility_vetted_views.json').write_text(json.dumps(selected,indent=2)+'\n');assert len(selected)==2,results;print('CORE104_CAMERA_VET_PASS',flush=True)
