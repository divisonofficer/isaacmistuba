"""Reference-directed chair back wrap and tapered outline, preserving seat/legs/materials."""
import bpy,json,hashlib
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree
ROOT=Path(__file__).resolve().parents[3];base=ROOT/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full';ref=ROOT/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';src=base/'scene_candidate_r43.blend';out=base/'scene_candidate_r44.blend';assert not out.exists();sha=hashlib.sha256(src.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(src));rows=[]
def warp(p):
 x,y,z=p;t=max(0,min(1,(z-.49)/.42));u=y/.22
 return Vector((x+.055*u*u-.015*t*t,y*(1-.12*t*t),z))
for o in list(bpy.data.objects):
 key=o.get('program_key','')
 if o.type!='MESH' or not key.startswith('breakout_chair') or not key.endswith('_back_upholstery'):continue
 o.data=o.data.copy();old=[v.co.copy() for v in o.data.vertices]
 for v in o.data.vertices:v.co=warp(v.co)
 o.data.update();welt=next(w for w in bpy.data.objects if w.get('program_key')==key.replace('_upholstery','_welt'));welt.data=welt.data.copy()
 for spline in welt.data.splines:
  for p in spline.points:p.co=(*warp(Vector(p.co[:3])),1)
 tree=BVHTree.FromPolygons([v.co.copy() for v in o.data.vertices],[list(f.vertices) for f in o.data.polygons]);gaps=[tree.find_nearest(Vector(p.co[:3]))[3] for spline in welt.data.splines for p in spline.points];assert max(gaps)<.002,max(gaps)
 rows.append({'object':o.name,'additional_corner_wrap_m':.055,'top_width_taper_fraction':.12,'additional_top_recline_m':.015,'maximum_vertex_displacement_m':max((v.co-p).length for v,p in zip(o.data.vertices,old)),'welt_max_surface_gap_m':max(gaps)})
assert len(rows)==4;bpy.ops.wm.save_as_mainfile(filepath=str(out));assert hashlib.sha256(src.read_bytes()).hexdigest()==sha;(ref/'realism_refinement_r44.json').write_text(json.dumps({'source':str(src),'source_sha256':sha,'candidate':str(out),'scope':'four upholstered chair backs and corresponding welt only;seats,legs,room layout,materials andlighting unchanged','changes':rows,'reference':'breakout_kitchen_reference_v1.png','rationale':'Reference has wrapped,tapered upholstered back rather than straight rectangular padded board. Native basic ChairFactory has rigid frame/bar variants;not blindly substituted for upholstered style.','photorealism_accepted':False,'requires':'same-camera close/wide visual comparison and support/clearance regression'},indent=2));print('SAVED',out,flush=True)
