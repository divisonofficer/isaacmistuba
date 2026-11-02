"""Actual native leaf motion samples and conservative planar fixture sweep envelopes."""
import bpy,json,math,hashlib,sys
from pathlib import Path
from mathutils import Vector,Matrix
from mathutils.bvhtree import BVHTree
from shapely.geometry import MultiPoint,LineString
from shapely.ops import unary_union
r=Path(__file__).resolve().parents[3];sys.path.insert(0,str(Path(__file__).parent));from wc_layout_checks import evaluated_geometry,bounds
d=r/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';src=r/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full/scene_candidate_r116_draft.blend';sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();source_sha=sha(src);bpy.ops.wm.open_mainfile(filepath=str(src));rows=[]
def geo(o):
 ev,me,ps=evaluated_geometry(o);fs=[tuple(f.vertices) for f in me.polygons];ev.to_mesh_clear();return ps,fs
for unit in [101,102]:
 door=next(o for o in bpy.context.scene.objects if o.get('program_key')==f'{unit}_core_wc_door');pivot=Vector(door['core104_hinge_world_m']);openangle=door['core104_open_angle_deg'];slots={i for i,m in enumerate(door.data.materials) if m and m.name.split('.')[0]!='office02_charcoal'};faces=[tuple(f.vertices) for f in door.data.polygons if f.material_index in slots];ids=sorted({i for f in faces for i in f});oldid={v:i for i,v in enumerate(ids)};faces=[tuple(oldid[v] for v in f) for f in faces];openps=[door.matrix_world@door.data.vertices[i].co for i in ids];radius=max((p-pivot).xy.length for p in openps);allposes=[]
 for step in range(46):
  angle=openangle*step/45;rot=Matrix.Translation(pivot)@Matrix.Rotation(math.radians(angle-openangle),4,'Z')@Matrix.Translation(-pivot);allposes.append((angle,[rot@p for p in openps]))
 sweepbounds=[(min(p[k] for _,ps in allposes for p in ps),max(p[k] for _,ps in allposes for p in ps)) for k in range(3)];obstacles=[]
 for o in bpy.context.scene.objects:
  if o.type!='MESH' or o==door:continue
  key=str(o.get('program_key',''));kind='fixture' if key.startswith(f'{unit}_core_wc') and not key.endswith('_door') else 'architecture' if o.name.endswith(('.wall','.exterior')) or o.name.startswith('Core104_') else None
  if not kind:continue
  lo,hi=bounds(o)
  if kind=='architecture' and any(hi[k]<sweepbounds[k][0]-.001 or lo[k]>sweepbounds[k][1]+.001 for k in range(3)):continue
  ps,fs=geo(o);obstacles.append((o.name,kind,BVHTree.FromPolygons(ps,fs),MultiPoint([(p.x,p.y) for p in ps]).convex_hull if kind=='fixture' else None))
 crossings=[]
 for angle,ps in allposes:
  t=BVHTree.FromPolygons(ps,faces)
  for name,kind,other,hull in obstacles:
   hits=t.overlap(other)
   if hits:crossings.append({'angle_deg':angle,'object':name,'kind':kind,'triangle_surface_crossings':len(hits)})
 # Segment hulls with sagitta cover bound continuous XY motion conservatively.
 segments=[]
 for (_,a),(_,b) in zip(allposes,allposes[1:]):segments.append(MultiPoint([(p.x,p.y) for p in a+b]).convex_hull)
 sagitta=radius*(1-math.cos(math.radians(abs(openangle)/45/2)));sweep=unary_union(segments).buffer(sagitta+1e-6,resolution=32);fixture_overlaps=[{'object':name,'swept_envelope_overlap_m2':sweep.intersection(hull).area,'distance_m':sweep.distance(hull)} for name,kind,t,hull in obstacles if kind=='fixture'];route_points=[(9.4,6.8),(7.45,6.8),(7.45,8.25),(8.45,8.25),(8.45,8.365)]
 if unit==102:route_points=[(21.5-x,y) for x,y in route_points]
 route=LineString(route_points).buffer(.3,resolution=32);open_hull=MultiPoint([(p.x,p.y) for p in openps]).convex_hull;route_overlaps=[{'object':door.name,'overlap_m2':route.intersection(open_hull).area}]+[{'object':name,'overlap_m2':route.intersection(hull).area} for name,kind,t,hull in obstacles if kind=='fixture'];rows.append({'unit':unit,'native_door':door.name,'hinge_world_m':list(pivot),'closed_to_open_angle_deg':[0,openangle],'pose_samples':46,'max_leaf_handle_radius_m':radius,'sagitta_bound_m':sagitta,'sampled_architecture_and_fixture_surface_crossings':crossings,'tested_obstacles':[{'object':name,'kind':kind} for name,kind,_,_ in obstacles],'continuous_conservative_xy_fixture_sweep':fixture_overlaps,'fully_open_leaf_and_fixture_vs600mm_planned_route':route_overlaps,'swept_envelope_xy':list(sweep.exterior.coords) if sweep.geom_type=='Polygon' else None,'scope':'Moving leaf/handle selection follows native non-charcoal material; own fixed casing/contact excluded.46 actual3D poses versus nearby walls/fixtures; conservative continuous XY envelope versus fixtures only.600mm proposed route tests current open leaf/fixtures only, not wall/floor navigability or all10rooms.'})
assert sha(src)==source_sha;out={'source':str(src),'source_sha256':source_sha,'rows':rows,'all_sampled_surface_poses_clear':all(not x['sampled_architecture_and_fixture_surface_crossings'] for x in rows),'all_conservative_fixture_sweeps_clear':all(y['swept_envelope_overlap_m2']<1e-9 for x in rows for y in x['continuous_conservative_xy_fixture_sweep']),'fully_open_planned_route_leaf_fixture_clear':all(y['overlap_m2']<1e-9 for x in rows for y in x['fully_open_leaf_and_fixture_vs600mm_planned_route']),'whole_navigation_accepted':False,'accepted':False};(d/'core116_native_door_sweep_audit.json').write_text(json.dumps(out,indent=2));print('CORE116_SWEEP',out['all_sampled_surface_poses_clear'],out['all_conservative_fixture_sweeps_clear'],out['fully_open_planned_route_leaf_fixture_clear']);print([(x['unit'],len(x['sampled_architecture_and_fixture_surface_crossings'])) for x in rows])
