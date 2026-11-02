"""Rigid pose search for broad cushion support, not just a single nearest vertex."""
import bpy,json,hashlib,math
from pathlib import Path
from mathutils import Vector,Matrix
from mathutils.bvhtree import BVHTree
R=Path(__file__).resolve().parents[3];D=R/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';B=R/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full';S=B/'scene_candidate_r98.blend';O=B/'scene_candidate_r99.blend';assert not O.exists();sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest();hs=sha(S);meta=json.loads((D/'realism_refinement_r98.json').read_text());bpy.ops.wm.open_mainfile(filepath=str(S));rows=meta['actual_pillows']['records'];results=[]
sofa=bpy.data.objects[rows[0]['sofa']];world=[sofa.matrix_world@v.co for v in sofa.data.vertices];lo=Vector([min(p[k] for p in world) for k in range(3)]);nm=sofa.matrix_world.to_3x3().inverted().transposed();sf=[];bf=[]
for f in sofa.data.polygons:
 n=(nm@f.normal).normalized();c=sofa.matrix_world@f.center
 if n.z>.35 and lo.z+.25<c.z<lo.z+.65 and c.x>lo.x+.25:sf.append(tuple(f.vertices))
 if n.x>.3 and c.z>lo.z+.4 and c.x<lo.x+.6:bf.append(tuple(f.vertices))
seat=BVHTree.FromPolygons(world,sf);back=BVHTree.FromPolygons(world,bf);whole=BVHTree.FromPolygons(world,[tuple(f.vertices) for f in sofa.data.polygons])
for record in rows:
 o=bpy.data.objects[record['object']];original=o.matrix_world.copy();pts=[original@v.co for v in o.data.vertices];center=Vector([(min(p[k] for p in pts)+max(p[k] for p in pts))/2 for k in range(3)]);trials=[];valid=[]
 # Roll around sofa-facing axis, recline around lateral axis. No scale/shape deformation.
 for pitch in [0,-10,-20]:
  for roll in [-30,-20,-10,0,10,20,30]:
   rotation=Matrix.Rotation(math.radians(pitch),4,'Y')@Matrix.Rotation(math.radians(roll),4,'X');mat=Matrix.Translation(center)@rotation@Matrix.Translation(-center)@original;anchor=mat.translation.copy();offsets=[mat@v.co-anchor for v in o.data.vertices];support=list(offsets)
   for face in o.data.polygons:
    ids=list(face.vertices);support.append(sum((offsets[j] for j in ids),Vector())/len(ids))
    for j,k in zip(ids,ids[1:]+ids[:1]):support.append((offsets[j]+offsets[k])*.5)
   cx,cy,cz=anchor
   for iteration in range(10):
    zs=[]
    for q in support:
     hit=seat.ray_cast(Vector((cx+q.x,cy+q.y,2)),Vector((0,0,-1)),3)[0]
     if hit is not None:zs.append(hit.z-q.z+.0012)
    if not zs:break
    cz=max(zs);xs=[]
    for q in support:
     hit=back.ray_cast(Vector((4,cy+q.y,cz+q.z)),Vector((-1,0,0)),5)[0]
     if hit is not None:xs.append(hit.x-q.x+.0012)
    if not xs:break
    cx=max(xs)
   placed=[q+Vector((cx,cy,cz)) for q in offsets];own=BVHTree.FromPolygons(placed,[tuple(f.vertices) for f in o.data.polygons]);overlap=len(own.overlap(whole));near={}
   for key,t in [('seat',seat),('back',back)]:
    close=[p for p in placed if t.find_nearest(p)[3]<.008];near[key]={'count':len(close),'span_y_m':max((p.y for p in close),default=0)-min((p.y for p in close),default=0),'minimum_gap_m':min(t.find_nearest(p)[3] for p in placed)}
   height=max(p.z for p in placed)-min(p.z for p in placed)
   score=min(near['seat']['span_y_m']/.20,1)+min(near['back']['span_y_m']/.15,1)-.002*abs(roll)-.001*abs(pitch)
   trial={'roll_deg':roll,'pitch_deg':pitch,'whole_sofa_surface_intersections':overlap,'near_support_8mm':near,'height_m':height,'score':score};trials.append(trial)
   if overlap==0 and height<.60 and max(v['minimum_gap_m'] for v in near.values())<.003:
    mat.translation=Vector((cx,cy,cz));valid.append((score,mat.copy(),trial))
   print('POSE_SCREEN',o.name,roll,pitch,'overlaps',overlap,'seat_span',near['seat']['span_y_m'],flush=True)
  # Keep intermediate diagnostics even if later search fails.
  (D/'pillow_r99_pose_search_partial.json').write_text(json.dumps({'completed_object_trials':results,'current_object':o.name,'trials':trials},indent=2))
 assert valid,o.name;score,chosen,best=max(valid,key=lambda x:x[0]);o.matrix_world=chosen
 record['matrix']=[list(v) for v in chosen];record['pose_refinement']=best;record['minimum_vertex_surface_gaps_m']={k:v['minimum_gap_m'] for k,v in best['near_support_8mm'].items()};record['triangle_surface_overlaps']={'seat':0,'back':0,'whole_sofa':best['whole_sofa_surface_intersections']};results.append({'object':o.name,'chosen':best,'trials':trials})
bpy.ops.wm.save_as_mainfile(filepath=str(O));assert sha(S)==hs;meta.update(source=str(S),source_sha256=hs,candidate=str(O),candidate_sha256=sha(O),change='Only two native101cushion rigid poses tuned by broad seat/back proximity span; source98 shape/UV/optics and all other scene objects preserved.',pillow_pose_refinement={'results':results,'limitation':'8mm vertex proximity span is a bounded support cue,not pressure distribution or mechanical stability. Whole-sofa triangle separation still required. RGB must reject perching/awkwardness.'},photorealism_accepted=False);(D/'realism_refinement_r99.json').write_text(json.dumps(meta,indent=2))
