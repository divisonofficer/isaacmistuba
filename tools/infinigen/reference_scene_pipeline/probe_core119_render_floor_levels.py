"""Diagnose RGB/semantic-floor disagreement using actual visible evaluated surfaces."""
import bpy,json
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree
r=Path(__file__).resolve().parents[3];d=r/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';src=r/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full/scene_candidate_r119_draft.blend';bpy.ops.wm.open_mainfile(filepath=str(src));dg=bpy.context.evaluated_depsgraph_get();rows=[];trees={}
for unit in [101,102]:
 for x in [8.65,8.85,9.0,9.15,9.35]:
  if unit==102:x=21.5-x
  y=6.75;hits=[]
  for o in bpy.context.scene.objects:
   if o.type!='MESH':continue
   eo=o.evaluated_get(dg);bb=[eo.matrix_world@Vector(v) for v in eo.bound_box]
   if not min(p.x for p in bb)-1e-5<=x<=max(p.x for p in bb)+1e-5 or not min(p.y for p in bb)-1e-5<=y<=max(p.y for p in bb)+1e-5 or min(p.z for p in bb)>.6:continue
   if o.name not in trees:
    me=eo.to_mesh();trees[o.name]=BVHTree.FromPolygons([eo.matrix_world@v.co for v in me.vertices],[list(f.vertices) for f in me.polygons]);eo.to_mesh_clear()
   loc,n,i,dist=trees[o.name].ray_cast(Vector((x,y,.6)),Vector((0,0,-1)),1)
   if loc is not None:hits.append({'object':o.name,'hit':list(loc),'visible_get':o.visible_get(),'hide_render':o.hide_render,'visible_camera':o.visible_camera,'collections':[c.name for c in o.users_collection]})
  rows.append({'unit':unit,'xy':[x,y],'hits_top_first':sorted(hits,key=lambda v:-v['hit'][2])})
(d/'core119_render_floor_level_probe.json').write_text(json.dumps(rows,indent=2));print([(x['unit'],x['xy'],[(h['object'],h['hit'][2],h['visible_get'],h['hide_render']) for h in x['hits_top_first'][:4]]) for x in rows])
