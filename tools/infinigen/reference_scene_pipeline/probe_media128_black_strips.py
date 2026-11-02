"""Identify actual rendered-surface candidates behind selected black-strip pixels."""
import bpy,json,math,sys
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree
r=Path(__file__).resolve().parents[3];sys.path.insert(0,str(Path(__file__).parent));from physical_scene_geometry import render_mesh_candidates,evaluated_surface
D=r/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';src=r/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full/scene_candidate_r128_draft.blend';bpy.ops.wm.open_mainfile(filepath=str(src));v=next(x for x in json.loads((D/'living125_matched_views.json').read_text()) if x['name']=='101_living_media_reverse');loc=Vector(v['location']);q=(Vector(v['target'])-loc).to_track_quat('-Z','Y');print('CAMERA',v,flush=True);physical,_=render_mesh_candidates();rays=[]
for px,py in [(500,230),(500,450),(830,430),(600,260),(600,550)]:
 h=960.;w=1280.;t=math.tan(math.radians(v.get('hfov_deg',v.get('hfov',85)))/2);direction=q@Vector(((2*(px+.5)/w-1)*t,(1-2*(py+.5)/h)*t*h/w,-1)).normalized();rays.append({'pixel':[px,py],'direction':direction,'hits':[]})
for o in physical:
 if not o.visible_camera:continue
 # Local region behind new media wall only, no claim of exhaustive first-hit across entire scene.
 p=[o.matrix_world@Vector(v) for v in o.bound_box];lo=[min(v[k] for v in p) for k in range(3)];hi=[max(v[k] for v in p) for k in range(3)]
 if hi[0]<6 or lo[0]>9 or hi[1]<7 or lo[1]>10 or hi[2]<.1:continue
 vs,fs,u=evaluated_surface(o);tree=BVHTree.FromPolygons(vs,fs,all_triangles=True)
 for ray in rays:
  hit,n,idx,dist=tree.ray_cast(loc,ray['direction'],20)
  if hit is not None:ray['hits'].append({'object':o.name,'distance_m':dist,'world_hit_m':list(hit),'normal':list(n),'materials':[m.name if m else None for m in o.data.materials]})
for ray in rays:ray['direction']=list(ray['direction']);ray['hits']=sorted(ray['hits'],key=lambda h:h['distance_m'])[:4]
(D/'media128_black_strip_surface_probe.json').write_text(json.dumps({'source':str(src),'view':v,'rays':rays,'scope':'Selected pixels cast through geometric camera to enabled render/camera-visible evaluated meshes in local media-wall region x6..9,y7..10. Local nearest candidates, not guaranteed full-scene rendered pixel ownership; shaders/alpha/light paths not evaluated.'},indent=2));print('BLACK_STRIP_SURFACE_PROBE',[(r['pixel'],[(h['object'],h['world_hit_m']) for h in r['hits'][:1]]) for r in rays],flush=True)
