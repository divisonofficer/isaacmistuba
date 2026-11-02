import bpy,json
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree
r=Path(__file__).resolve().parents[3];d=r/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';a=json.loads((d/'core116_route_volume_audit.json').read_text());bpy.ops.wm.open_mainfile(filepath=a['source']);dg=bpy.context.evaluated_depsgraph_get();trees={};rows=[]
for row in a['rows']:
 for sample in row['centreline_floor_samples']:
  if sample['floor_hit']:continue
  x,y=sample['xy'];hits=[]
  for o in bpy.context.scene.objects:
   if o.type!='MESH':continue
   eo=o.evaluated_get(dg);bb=[eo.matrix_world@Vector(v) for v in eo.bound_box]
   if not min(v.x for v in bb)-1e-5<=x<=max(v.x for v in bb)+1e-5 or not min(v.y for v in bb)-1e-5<=y<=max(v.y for v in bb)+1e-5 or min(v.z for v in bb)>.159:continue
   if o.name not in trees:
    me=eo.to_mesh();trees[o.name]=BVHTree.FromPolygons([eo.matrix_world@v.co for v in me.vertices],[list(f.vertices) for f in me.polygons]);eo.to_mesh_clear()
   loc,n,i,dist=trees[o.name].ray_cast(Vector((x,y,.159)),Vector((0,0,-1)),2)
   if loc is not None:hits.append({'object':o.name,'hit':list(loc),'distance_m':dist,'object_hide_render':o.hide_render})
  rows.append({'unit':row['unit'],'xy':[x,y],'all_mesh_downward_hits':sorted(hits,key=lambda v:v['distance_m'])[:6]})
(d/'core116_threshold_floor_probe.json').write_text(json.dumps(rows,indent=2));print([(x['unit'],x['xy'],[(h['object'],h['hit'][2]) for h in x['all_mesh_downward_hits'][:2]]) for x in rows])
