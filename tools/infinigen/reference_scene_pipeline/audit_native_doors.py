"""Actual triangle intersections between native door meshes and scene furniture.
Casings, walls and intentional hinge contacts are outside this fixture gate.
"""
import bpy,json,argparse,sys,hashlib
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree
p=argparse.ArgumentParser();p.add_argument('--blend',type=Path,required=True);p.add_argument('--out',type=Path,required=True);a=p.parse_args(sys.argv[sys.argv.index('--')+1:] if '--' in sys.argv else sys.argv[1:]);bpy.ops.wm.open_mainfile(filepath=str(a.blend.resolve()))
def bounds(o):
 used={i for f in o.data.polygons for i in f.vertices};vs=[o.matrix_world@o.data.vertices[i].co for i in used]
 return [(min(v[k] for v in vs),max(v[k] for v in vs)) for k in range(3)] if vs else None
def overlaps(a,b):return all(min(a[k][1],b[k][1])-max(a[k][0],b[k][0])>1e-5 for k in range(3))
cache={}
def tree(o):
 if o.name not in cache:cache[o.name]=BVHTree.FromPolygons([o.matrix_world@v.co for v in o.data.vertices],[list(f.vertices) for f in o.data.polygons])
 return cache[o.name]
fixtures=[(o,bounds(o)) for o in bpy.data.objects if o.type=='MESH' and o.get('reference_scene_owner') and o.get('audit_kind','furniture') in ('fixture','furniture','ground_container')];records=[];errors=[]
for o in bpy.data.objects:
 if o.type!='MESH' or 'DoorFactory' not in o.name:continue
 db=bounds(o);hits=[]
 if db is None:continue
 for fixture,fb in fixtures:
  if fb is None or not overlaps(db,fb):continue
  pairs=tree(o).overlap(tree(fixture))
  if pairs:hits.append({'object':fixture.name,'program_key':fixture.get('program_key'),'triangle_intersection_pairs':len(pairs),'axis_overlap_m':[min(db[k][1],fb[k][1])-max(db[k][0],fb[k][0]) for k in range(3)]})
 row={'door':o.name,'refitted':bool(o.get('native_door_refit')),'state':o.get('door_state','native_generated_pose'),'fixture_hits':hits};records.append(row)
 if hits:errors.append(row)
doc={'source':str(a.blend.resolve()),'source_sha256':hashlib.sha256(a.blend.read_bytes()).hexdigest(),'status':'pass_native_door_fixture_triangles' if not errors else 'needs_door_fixture_repair','door_count':len(records),'doors':records,'errors':errors,'limitations':['Raw native mesh triangles; modifiers are not evaluated.','Checks current pose only, not complete swing paths or navigation motion.','Excludes casing/hinge, architectural walls and floor contacts.','Surface intersections do not prove absence of contained solids.'],'visual_acceptance':False};a.out.write_text(json.dumps(doc,indent=2));print(json.dumps({'doors':len(records),'errors':len(errors),'status':doc['status']}),flush=True)
