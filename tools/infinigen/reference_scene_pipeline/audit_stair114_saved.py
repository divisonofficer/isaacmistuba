"""Reopen inferred stair exit: tread heights, post support and finite upper boundary."""
import bpy,json,hashlib,bmesh
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree
r=Path(__file__).resolve().parents[3];d=r/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';a=json.loads((d/'stair114_upper_connection.json').read_text());assert hashlib.sha256(Path(a['candidate']).read_bytes()).hexdigest()==a['candidate_sha256'];bpy.ops.wm.open_mainfile(filepath=a['candidate']);floor=bpy.data.objects['bedroom_0/0.floor'];fz=max((floor.matrix_world@Vector(c)).z for c in floor.bound_box);verts=[];faces=[];top=[]
for o in bpy.context.scene.objects:
 if o.type!='MESH' or o.get('audit_kind')!='stair_structure':continue
 base=len(verts);verts.extend(o.matrix_world@v.co for v in o.data.vertices);faces.extend(tuple(base+i for i in f.vertices) for f in o.data.polygons);bm=bmesh.new();bm.from_mesh(o.data);nm=sum(not e.is_manifold for e in bm.edges);bm.free();top.append({'object':o.name,'nonmanifold_edges':nm});assert nm==0
t=BVHTree.FromPolygons(verts,faces);treads=[]
for name,x,y0,sgn,pitch,z0 in [('lower',9.9,11.65,1,.29,fz),('upper',11.6,14.26,-1,.24,fz+1.35)]:
 for i in range(9):
  y=y0+sgn*(i+.5)*pitch;z=z0+(i+1)*.15;hit=t.ray_cast(Vector((x,y,z+.1)),Vector((0,0,-1)),.3)[0];assert hit is not None;error=abs(hit.z-z);assert error<1e-5;treads.append({'flight':name,'step':i,'height_error_m':error})
posts=[]
for o in bpy.context.scene.objects:
 if o.type!='MESH' or o.get('audit_kind')!='stair_guard' or 'post' not in o.name.lower():continue
 ps=[o.matrix_world@v.co for v in o.data.vertices];low=min(v.z for v in ps);points=[v for v in ps if v.z<low+.0001];gaps=[]
 for q in points:
  hit=t.ray_cast(q+Vector((0,0,.02)),Vector((0,0,-1)),.12)[0];assert hit is not None,(o.name,'unsupported');gaps.append(q.z-hit.z)
 assert min(gaps)>=-.003 and max(gaps)<.003,(o.name,gaps);posts.append({'object':o.name,'supported_samples':len(gaps),'max_abs_gap_m':max(abs(x) for x in gaps)})
deps=bpy.context.evaluated_depsgraph_get();bound=[]
for x in [9.5,10.5,11.6,12.25]:
 for z in [fz+3.5,fz+4.2,fz+5.1]:
  hit,pt,n,i,o,m=bpy.context.scene.ray_cast(deps,Vector((x,12.0,z)),Vector((0,-1,0)),distance=2);assert hit,(x,z,'exit boundary leak');assert 'upper_exit' in o.name,(o.name,x,z);bound.append({'x':x,'z':z,'hit':o.name,'point':list(pt)})
assert len(posts)==41
report={'pass':True,'candidate_sha256':a['candidate_sha256'],'new_structure_topology':top,'treads':treads,'post_support':posts,'upper_exit_boundary_rays':bound,'scope':'Saved manifold structure,18 tread center heights,41 post low-vertex support,12 north-exit rays. No full swept-body collision, all-floor navigation, door swing/fire code or photorealism certification.'};(d/'stair114_saved_audit.json').write_text(json.dumps(report,indent=2));print('STAIR114_SAVED_GEOMETRY_PASS')
