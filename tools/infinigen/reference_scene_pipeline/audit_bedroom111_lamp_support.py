"""Actual mesh-ray lamp support audit; bbox height is not tabletop height."""
import bpy,json
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree
r=Path(__file__).resolve().parents[3];d=r/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';a=json.loads((d/'bedroom110_build.json').read_text());bpy.ops.wm.open_mainfile(filepath=json.loads((d/'bedroom111_support_fix.json').read_text())['candidate']);rows=[]
for row in a['replacements']:
 objs=[bpy.data.objects[n] for n in row['new_objects']];verts=[];faces=[]
 for o in objs:
  base=len(verts);verts.extend(o.matrix_world@v.co for v in o.data.vertices);faces.extend(tuple(base+i for i in f.vertices) for f in o.data.polygons)
 t=BVHTree.FromPolygons(verts,faces);lamps=[bpy.data.objects[n] for n in row['lamp_objects_moved'] if bpy.data.objects[n].type=='MESH'];assert lamps
 o=min(lamps,key=lambda o:min((o.matrix_world@v.co).z for v in o.data.vertices));ps=[o.matrix_world@v.co for v in o.data.vertices];minz=min(v.z for v in ps);points=[v for v in ps if v.z<minz+.0001];gaps=[]
 for v in points:
  hit=t.ray_cast(v+Vector((0,0,.02)),Vector((0,0,-1)),.15)[0]
  if hit:gaps.append(v.z-hit.z)
 assert gaps;rows.append({'lamp_base':o.name,'sample_count':len(points),'table_hit_count':len(gaps),'min_gap_m':min(gaps),'max_gap_m':max(gaps),'pass':len(gaps)==len(points) and min(gaps)>-.0001 and max(gaps)<.001})
report={'pass':all(x['pass'] for x in rows),'rows':rows,'scope':'Low native lamp-body vertex rays against new tabletop mesh; no stability/nav/visual acceptance.'};(d/'bedroom111_lamp_support_audit.json').write_text(json.dumps(report,indent=2));print(json.dumps(report))
