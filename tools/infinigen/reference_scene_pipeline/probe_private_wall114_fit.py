"""Measure existing wall surfaces at prospective window perimeter; no scene edits."""
import bpy,json
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree
r=Path(__file__).resolve().parents[3];d=r/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';a=json.loads((d/'private_windows114_source_probe.json').read_text());bpy.ops.wm.open_mainfile(filepath=a['source']);rows=[]
for room in a['rooms']:
 o=bpy.data.objects[room['wall_object']];verts=[o.matrix_world@v.co for v in o.data.vertices];tree=BVHTree.FromPolygons(verts,[list(p.vertices) for p in o.data.polygons],all_triangles=False)
 y=sum(p[1] for p in room['polygon'])/len(room['polygon']);hits=[]
 for dy in [-1.05,0,1.05]:
  for z in [.17,1.3,2.52]:
   origin=Vector((2,y+dy,z));direction=Vector((-1,0,0));loc,n,idx,dist=tree.ray_cast(origin,direction,4)
   hits.append({'y':y+dy,'z':z,'surface':list(loc) if loc else None,'normal':list(n) if n else None})
 rows.append({'room':room['room'],'wall':o.name,'wall_vertices':len(verts),'wall_faces':len(o.data.polygons),'wall_modifiers':[m.type for m in o.modifiers],'wall_bounds':[[min(v[k] for v in verts) for k in range(3)],[max(v[k] for v in verts) for k in range(3)]],'prospective_perimeter_samples':hits})
out={'source':a['source'],'rooms':rows,'scope':'Raw actual wall ray measurements only, no fit approval or scene edits.'};(d/'private_wall114_fit_probe.json').write_text(json.dumps(out,indent=2));print('PRIVATE_WALL114_PROBED',len(rows))
