"""Measured drawer reveals and closed folded2mm sheet fronts,not a blanket gap cover or shader darkening."""
import bpy,bmesh,json,hashlib
from pathlib import Path
from mathutils import Matrix
r=Path('/jarvis/project/robomituba');base=r/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full';ref=r/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';src=base/'scene_candidate_r71.blend';out=base/'scene_candidate_r72.blend';assert not out.exists();sha=hashlib.sha256(src.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(src));records=[]
for o in [x for x in bpy.data.objects if x.get('program_key') in ['support_west_storage','support_east_storage']]:
 adj={v.index:set() for v in o.data.vertices}
 for e in o.data.edges:a,b=e.vertices;adj[a].add(b);adj[b].add(a)
 unseen=set(adj);fronts=[]
 while unseen:
  todo=[unseen.pop()];ids=set(todo)
  while todo:
   for i in adj[todo.pop()]:
    if i in unseen:unseen.remove(i);ids.add(i);todo.append(i)
  vs=[o.data.vertices[i].co for i in ids];lo=[min(v[k] for v in vs) for k in range(3)];hi=[max(v[k] for v in vs) for k in range(3)]
  if len(ids)==8 and abs(lo[0]-.22)<1e-5 and abs(hi[0]-.232)<1e-5 and abs(lo[1]+.437)<1e-5 and hi[2]-lo[2]>.3:fronts.append((ids,lo,hi))
 assert len(fronts)==2;fronts.sort(key=lambda x:x[1][2]);remove=set().union(*(f[0] for f in fronts));mi=next(p.material_index for p in o.data.polygons if p.vertices[0] in remove);mat=o.data.materials[mi];bm=bmesh.new();bm.from_mesh(o.data);bm.verts.ensure_lookup_table();bmesh.ops.delete(bm,geom=[bm.verts[i] for i in remove],context='VERTS');bm.to_mesh(o.data);bm.free();o.data.update()
 for j,(_,lo,hi) in enumerate(fronts):
  zl=.0515 if j==0 else .411;zh=.409 if j==0 else .7585;half=.4385;t=.002;vs=[]
  for x,w,low,high in [(.232,half,zl,zh),(.220,half,zl,zh),(.220,half-t,zl+t,zh-t),(.230,half-t,zl+t,zh-t)]:vs.extend([(x,-w,low),(x,w,low),(x,w,high),(x,-w,high)])
  fs=[(0,1,2,3),(15,14,13,12)]+[(a+k,a+(k+1)%4,a+4+(k+1)%4,a+4+k) for a in [0,4,8] for k in range(4)];me=bpy.data.meshes.new('FoldedFront_'+str(j)+'_'+o['program_key']);me.from_pydata(vs,[],fs);me.materials.append(mat);bm=bmesh.new();bm.from_mesh(me);bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces));bad=sum(not e.is_manifold for e in bm.edges);bm.to_mesh(me);bm.free();assert bad==0
  ch=bpy.data.objects.new(me.name,me);bpy.context.collection.objects.link(ch);ch.parent=o;ch.matrix_parent_inverse=Matrix.Identity(4);ch.matrix_basis=Matrix.Identity(4);ch['program_key']=o['program_key']+'_folded_front_'+str(j);ch['audit_kind']='detail';be=ch.modifiers.new('Fold radius','BEVEL');be.width=.00045;be.segments=3
  records.append({'cabinet':o.name,'drawer_index':j,'previous_side_reveal_m':.003,'new_side_reveal_m':.0015,'previous_top_reveal_m':.0035 if j==1 else None,'new_top_reveal_m':.0015 if j==1 else None,'new_between_drawers_reveal_m':.002,'front_sheet_thickness_m':t,'return_depth_m':.012,'raw_nonmanifold_edges':bad,'unchanged':'cabinet envelope,top/sides/headers,handles,materials,lights,cameras andshelf/books/support'})
assert len(records)==4;bpy.context.view_layer.update();bpy.ops.wm.save_as_mainfile(filepath=str(out));assert hashlib.sha256(src.read_bytes()).hexdigest()==sha;(ref/'realism_refinement_r72.json').write_text(json.dumps({'source':str(src),'source_sha256':sha,'candidate':str(out),'trigger':'Full16 review: peripheral blackfiler reveals look open. Source probe measured3mm side/3.5mm top,not missing carcass. Reduce precisely and replace12mm solidfront by2mm closedfolded shell.','changes':records,'photorealism_accepted':False,'requires':'Savedsource audits andsame2views direct/blind acceptance. No fullscene structural certification.'},indent=2));print('Saved',out,flush=True)
