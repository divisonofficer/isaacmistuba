"""Reopen saved candidate and test clear pane rays against native wall layers."""
import bpy,json,math
from pathlib import Path
from mathutils import Vector,Matrix
from mathutils.bvhtree import BVHTree
r=Path(__file__).resolve().parents[3];d=r/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';a=json.loads((d/'glazing114_build.json').read_text());bpy.ops.wm.open_mainfile(filepath=a['candidate']);rows=[]
for row in a['rooms']:
 pose=Matrix(row['pose']);tests=[]
 for layer in row['cuts']:
  o=bpy.data.objects[layer['object']];tree=BVHTree.FromPolygons([o.matrix_world@v.co for v in o.data.vertices],[list(f.vertices) for f in o.data.polygons]);hits=[]
  for x in [-.9,-.5,.5,.9]:
   for z in [.15,1.1,2.25]:
    origin=pose@Vector((x,-.5,z));direction=pose.to_3x3()@Vector((0,1,0));loc,n,i,dist=tree.ray_cast(origin,direction,1)
    if loc:hits.append(list(loc))
  tests.append({'wall':o.name,'sample_count':12,'blocking_hits':hits})
 o=bpy.data.objects[row['object']];rows.append({'room':row['room'],'native_scale':list(o.scale),'wall_tests':tests})
out={'source':a['candidate'],'rooms':rows,'sampled_wall_apertures_clear':all(not t['blocking_hits'] for row in rows for t in row['wall_tests']),'scope':'12 clear-pane rays per raw wall layer; does not certify evaluated modifier seams, reveals, weather seals, furniture or global navigation. Visual acceptance pending.'};(d/'glazing114_aperture_audit.json').write_text(json.dumps(out,indent=2));assert out['sampled_wall_apertures_clear'];print('GLAZING114_RAW_APERTURES_CLEAR')
