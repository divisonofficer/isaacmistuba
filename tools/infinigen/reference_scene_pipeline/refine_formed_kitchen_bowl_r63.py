"""Manufactured continuous sink bowl/rim and open drain after actual cabinet-void fix; existing metal shader retained."""
import bpy,bmesh,json,hashlib,math
from pathlib import Path
from mathutils import Matrix
r=Path('/jarvis/project/robomituba');base=r/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full';ref=r/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';src=base/'scene_candidate_r62.blend';out=base/'scene_candidate_r63.blend';assert not out.exists();sha=hashlib.sha256(src.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(src));records=[];prior=json.loads((ref/'realism_refinement_r62.json').read_text())['changes']
for c in prior:
 o=bpy.data.objects[c['kitchen']];sy=c['sink_center_y_local'];adj={v.index:set() for v in o.data.vertices}
 for e in o.data.edges:a,b=e.vertices;adj[a].add(b);adj[b].add(a)
 unseen=set(adj);remove=set();removed=[]
 while unseen:
  todo=[unseen.pop()];ids=set(todo)
  while todo:
   for i in adj[todo.pop()]:
    if i in unseen:unseen.remove(i);ids.add(i);todo.append(i)
  vs=[o.data.vertices[i].co for i in ids];lo=[min(v[k] for v in vs) for k in range(3)];hi=[max(v[k] for v in vs) for k in range(3)]
  if lo[0]>.08 and hi[0]<.56 and lo[1]>sy-.33 and hi[1]<sy+.33 and lo[2]>.70 and hi[2]<.89:remove.update(ids);removed.append([lo,hi])
 assert len(remove)==64 and len(removed)==6,(o.name,len(remove),removed);mi=next(p.material_index for p in o.data.polygons if p.vertices[0] in remove);mat=o.data.materials[mi];bm=bmesh.new();bm.from_mesh(o.data);bm.verts.ensure_lookup_table();bmesh.ops.delete(bm,geom=[bm.verts[i] for i in remove],context='VERTS');bm.to_mesh(o.data);bm.free();o.data.update()
 profile=[(.022,.022,.724,2),(.15,.23,.728,5),(.18,.265,.752,6),(.19,.278,.885,7),(.195,.283,.896,7),(.235,.315,.898,8),(.235,.315,.901,8),(.195,.283,.901,7),(.19,.278,.897,7),(.185,.273,.885,7),(.175,.258,.755,6),(.145,.225,.735,5),(.065,.08,.730,3),(.022,.022,.727,2)]
 vs=[];N=128
 for rx,ry,z,power in profile:
  for k in range(N):
   a=k*math.tau/N;co=math.cos(a);si=math.sin(a);vs.append((.32+rx*math.copysign(abs(co)**(2/power),co),sy+ry*math.copysign(abs(si)**(2/power),si),z))
 fs=[(j*N+k,j*N+(k+1)%N,((j+1)%len(profile))*N+(k+1)%N,((j+1)%len(profile))*N+k) for j in range(len(profile)) for k in range(N)];me=bpy.data.meshes.new('FormedSink_'+o['program_key']);me.from_pydata(vs,[],fs);me.materials.append(mat);bm=bmesh.new();bm.from_mesh(me);bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces));bad=sum(not e.is_manifold for e in bm.edges);bm.to_mesh(me);bm.free();assert bad==0
 for f in me.polygons:f.use_smooth=True
 child=bpy.data.objects.new('FormedSink_'+o['program_key'],me);bpy.context.collection.objects.link(child);child.parent=o;child.matrix_parent_inverse=Matrix.Identity(4);child.matrix_basis=Matrix.Identity(4);child['program_key']=o['program_key']+'_formed_sink_shell';child['audit_kind']='detail';sub=child.modifiers.new('Continuous draw radii','SUBSURF');sub.levels=1;sub.render_levels=1
 records.append({'kitchen':o.name,'removed_primitives':6,'removed_vertices':64,'shell_closed_nonmanifold_edges':bad,'actual_open_drain_diameter_m':.044,'outer_rim_m':[.47,.63],'inner_mouth_m':[.38,.556],'rim_top_local_z_m':.901,'bowl_lowest_inner_z_m':.727,'material_unchanged':mat.name,'note':'Retains source62 cabinet void. No newlighting/shader andno claim of drain plumbing completion.'})
bpy.context.view_layer.update();bpy.ops.wm.save_as_mainfile(filepath=str(out));assert hashlib.sha256(src.read_bytes()).hexdigest()==sha;(ref/'realism_refinement_r63.json').write_text(json.dumps({'source':str(src),'source_sha256':sha,'candidate':str(out),'changes':records,'trigger':'r62 cavity exists but102 stillreads flatdark patch; continuous formed bowl,rim anddrain geometry trial only','photorealism_accepted':False,'requires':'Saved-source audits andsame-camera two-view direct/blind comparison'},indent=2));print('Saved',out,flush=True)
