"""Shallow seat compression and surface-following topstitching, kept separate from UV comparison."""
import bpy,math,json,hashlib
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree
ROOT=Path(__file__).resolve().parents[3];base=ROOT/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full';ref=ROOT/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';src=base/'scene_candidate_r39.blend';out=base/'scene_candidate_r40.blend';assert not out.exists();sha=hashlib.sha256(src.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(src));rows=[]
thread=bpy.data.materials.new('BreakoutR40_blue_sewing_thread');thread.use_nodes=True;bs=thread.node_tree.nodes.get('Principled BSDF');bs.inputs['Base Color'].default_value=(.045,.082,.12,1);bs.inputs['Roughness'].default_value=.83
for o in list(bpy.data.objects):
 key=o.get('program_key','')
 if o.type!='MESH' or not key.startswith('breakout_chair') or '_seat_upholstery' not in key:continue
 o.data=o.data.copy();maximum=0
 for v in o.data.vertices:
  x,y,z=v.co
  if z<=.44:continue
  envelope=max(0,1-(x/.23)**4)*max(0,1-(y/.23)**4);fade=min(1,(z-.44)/.025);delta=.004*math.exp(-((x-.025)/.13)**2-((y+.01)/.15)**2)*envelope*fade;v.co.z-=delta;maximum=max(maximum,delta)
 o.data.update();tree=BVHTree.FromPolygons([v.co for v in o.data.vertices],[list(f.vertices) for f in o.data.polygons]);welt=next(w for w in bpy.data.objects if w.get('program_key')==key.replace('_upholstery','_welt'));points=[Vector(p.co[:3]) for p in welt.data.splines[0].points];projected=[];maxgap=0
 for p in points:
  target=Vector((p.x*.985,p.y*.985,p.z+.002));hit,normal,_,dist=tree.find_nearest(target);assert hit is not None;projected.append(hit+normal*.00018)
 curve=bpy.data.curves.new('Topstitch_4mm_pitch','CURVE');curve.dimensions='3D';curve.bevel_depth=.00015;curve.bevel_resolution=2;count=0
 # Walk the perimeter by physical arclength rather than one stitch per mesh segment.
 accum=0;segments=[]
 for a,b in zip(projected,projected[1:]):
  length=(b-a).length;segments.append((accum,accum+length,a,b));accum+=length
 for distance in [i*.004 for i in range(int(accum/.004))]:
  def point_at(d):
   for lo,hi,a,b in segments:
    if lo<=d<=hi:return a.lerp(b,(d-lo)/(hi-lo))
   return projected[-1]
  pts=[]
  for d in [distance,min(distance+.0022,accum)]:
   guess=point_at(d);hit,normal,_,_=tree.find_nearest(guess);q=hit+normal*.00018;maxgap=max(maxgap,tree.find_nearest(q)[3]);pts.append(q)
  spline=curve.splines.new('POLY');spline.points.add(1)
  for dst,p in zip(spline.points,pts):dst.co=(*p,1)
  count+=1
 curve.materials.append(thread);sew=bpy.data.objects.new('BreakoutR40_seat_topstitch',curve);bpy.context.scene.collection.objects.link(sew);sew.parent=o.parent;sew['reference_scene_owner']='commercial_office_floor_02';sew['program_key']=key.replace('_upholstery','_topstitch');sew['audit_kind']='detail';assert maxgap<.0003
 rows.append({'object':o.name,'maximum_seat_compression_m':maximum,'stitch_count':count,'thread_radius_m':.00015,'pitch_m':.004,'nominal_thread_to_body_gap_m':.00018,'maximum_measured_gap_m':maxgap})
assert len(rows)==4;bpy.ops.wm.save_as_mainfile(filepath=str(out));assert hashlib.sha256(src.read_bytes()).hexdigest()==sha;(ref/'realism_refinement_r40.json').write_text(json.dumps({'source':str(src),'candidate':str(out),'source_sha256':sha,'trigger':'Independent r38: uniformly rounded pads and seam reads as boundary only','scope':'4 seat pads only: shallow broad4mm max compression,0.3mm diameter thread,4mm pitch topstitch projected onto actual changed seat surface. No arbitrary dirt or noise.','seats':rows,'lighting_exposure':'unchanged','photorealism_accepted':False,'requires':'same-camera comparison against39;contact/whole scene regression;independent review'},indent=2));print('SAVED',out,flush=True)
