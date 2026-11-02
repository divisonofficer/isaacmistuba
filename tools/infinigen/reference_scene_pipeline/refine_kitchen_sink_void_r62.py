"""Remove actual solid-cabinet fill from two existing recessed sink bowls; all sink/counter/camera/materials retained."""
import bpy,bmesh,json,hashlib
from pathlib import Path
from mathutils import Vector,Matrix
from mathutils.bvhtree import BVHTree
r=Path('/jarvis/project/robomituba');base=r/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full';ref=r/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';src=base/'scene_candidate_r61.blend';out=base/'scene_candidate_r62.blend';assert not out.exists();sha=hashlib.sha256(src.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(src));records=[]
def ray(o,x,y):
 tree=BVHTree.FromPolygons([v.co.copy() for v in o.data.vertices],[tuple(p.vertices) for p in o.data.polygons]);hit,n,i,d=tree.ray_cast(Vector((x,y,.95)),Vector((0,0,-1)),.4);assert hit is not None;return {'z':hit.z,'material':o.data.materials[o.data.polygons[i].material_index].name}
def box(name,low,hi,mat,parent):
 vs=[(x,y,z) for x,y,z in [(low[0],low[1],low[2]),(hi[0],low[1],low[2]),(hi[0],hi[1],low[2]),(low[0],hi[1],low[2]),(low[0],low[1],hi[2]),(hi[0],low[1],hi[2]),(hi[0],hi[1],hi[2]),(low[0],hi[1],hi[2])]];fs=[(0,3,2,1),(4,5,6,7),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)];me=bpy.data.meshes.new(name);me.from_pydata(vs,[],fs);me.materials.append(mat);o=bpy.data.objects.new(name,me);bpy.context.collection.objects.link(o);o.parent=parent;o.matrix_parent_inverse=Matrix.Identity(4);o.matrix_basis=Matrix.Identity(4);o['program_key']=parent['program_key']+'_void_carcass_'+name;o['audit_kind']='detail';return o
objs=[o for o in bpy.data.objects if o.type=='MESH' and str(o.get('program_key','')).endswith('_kitchen_run')];assert len(objs)==2
for o in objs:
 adj={v.index:set() for v in o.data.vertices}
 for e in o.data.edges:a,b=e.vertices;adj[a].add(b);adj[b].add(a)
 todo=[min(adj)];ids=set(todo)
 while todo:
  for i in adj[todo.pop()]:
   if i not in ids:ids.add(i);todo.append(i)
 vs=[o.data.vertices[i].co for i in ids];lo=[min(v[k] for v in vs) for k in range(3)];hi=[max(v[k] for v in vs) for k in range(3)];assert len(ids)==8 and abs(lo[0])<1e-5 and abs(hi[0]-.6)<1e-5 and abs(hi[2]-.86)<1e-5,(o.name,lo,hi)
 matidx=next(p.material_index for p in o.data.polygons if p.vertices[0] in ids);mat=o.data.materials[matidx]
 # Existing native sink floor is the isolated8-vertex slab at z.71-.73. Derive its centre from mesh,not a copied hardcoded room pose.
 floors=[v.co for v in o.data.vertices if .709<v.co.z<.731 and .09<v.co.x<.55];assert floors;sy=(min(v.y for v in floors)+max(v.y for v in floors))/2
 before=ray(o,.32,sy+.10);assert abs(before['z']-.86)<1e-4,before
 bm=bmesh.new();bm.from_mesh(o.data);bm.verts.ensure_lookup_table();bmesh.ops.delete(bm,geom=[bm.verts[i] for i in ids],context='VERTS');bm.to_mesh(o.data);bm.free();o.data.update()
 parts=[(lo,[hi[0],hi[1],.70]),([lo[0],lo[1],.70],[hi[0],sy-.32,hi[2]]),([lo[0],sy+.32,.70],hi),([lo[0],sy-.32,.70],[.085,sy+.32,hi[2]]),([.56,sy-.32,.70],[hi[0],sy+.32,hi[2]])]
 for i,(low,high) in enumerate(parts):assert all(high[k]>low[k] for k in range(3));box('SinkVoid_'+str(i)+'_'+o['program_key'],low,high,mat,o)
 after=ray(o,.32,sy+.10);assert abs(after['z']-.73)<1e-4,after
 records.append({'kitchen':o.name,'sink_center_y_local':sy,'before_first_hit':before,'after_first_hit':after,'removed_cabinet_fill_depth_m':.16,'void_local_bounds':[[.085,sy-.32,.70],[.56,sy+.32,.86]],'new_carcass_parts':5,'unchanged':'Existing bowl/walls/drain/faucet/countertop/fronts/materials/lights/cameras retained'})
bpy.context.view_layer.update();bpy.ops.wm.save_as_mainfile(filepath=str(out));assert hashlib.sha256(src.read_bytes()).hexdigest()==sha;(ref/'realism_refinement_r62.json').write_text(json.dumps({'source':str(src),'source_sha256':sha,'candidate':str(out),'trigger':'Full39 blind review flat sink perception; actual mesh probe found solid base body top z.86 inside bowl whose floor is z.73','changes':records,'photorealism_accepted':False,'requires':'Source-bound saved audits,source62 evaluated assembly rays including new carcass,and identical-camera kitchen views before adoption'},indent=2));print('Saved',out,flush=True)
