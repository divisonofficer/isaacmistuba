"""Repair six actual monitor-to-desk support gaps; move complete display assembly,not entire desk orcamera."""
import bpy,json,hashlib
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree
r=Path('/jarvis/project/robomituba');base=r/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full';ref=r/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';src=base/'scene_candidate_r71.blend';out=base/'scene_candidate_r73.blend';assert not out.exists();sha=hashlib.sha256(src.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(src));rows=[]
for o in [x for x in bpy.data.objects if x.type=='MESH' and str(x.get('program_key','')).startswith('private_') and str(x.get('program_key','')).endswith('_desk')]:
 adj={v.index:set() for v in o.data.vertices}
 for e in o.data.edges:a,b=e.vertices;adj[a].add(b);adj[b].add(a)
 unseen=set(adj);parts=[]
 while unseen:
  todo=[unseen.pop()];ids=set(todo)
  while todo:
   for i in adj[todo.pop()]:
    if i in unseen:unseen.remove(i);ids.add(i);todo.append(i)
  vs=[o.data.vertices[i].co for i in ids];lo=[min(v[k] for v in vs) for k in range(3)];hi=[max(v[k] for v in vs) for k in range(3)];parts.append((ids,lo,hi))
 bases=[p for p in parts if all(abs((p[2][k]-p[1][k])-d)<1e-5 for k,d in enumerate([.18,.22,.012]))];stems=[p for p in parts if all(abs((p[2][k]-p[1][k])-d)<1e-5 for k,d in enumerate([.03,.05,.2]))];assert len(bases)==len(stems)==1,(o.name,len(bases),len(stems));ids,lo,hi=bases[0];cx=(lo[0]+hi[0])/2;cy=(lo[1]+hi[1])/2;tree=BVHTree.FromPolygons([v.co.copy() for v in o.data.vertices],[tuple(p.vertices) for p in o.data.polygons]);hit,n,index,dist=tree.ray_cast(Vector((cx,cy,lo[2]-.0001)),Vector((0,0,-1)),.2);assert hit is not None and abs(hit.z-.75)<1e-5;gap=lo[2]-hit.z;assert .06<gap<.07,(o.name,gap);delta=hit.z-lo[2]
 native_ids=ids|stems[0][0]
 for i in native_ids:o.data.vertices[i].co.z+=delta
 children=[x for x in bpy.data.objects if x.parent==o and '_monitor_' in str(x.get('program_key',''))];assert len(children) in [3,6],(o.name,[x.name for x in children])
 for x in children:x.location.z+=delta
 o.data.update();newgap=min(o.data.vertices[i].co.z for i in ids)-hit.z;assert abs(newgap)<1e-6
 rows.append({'desk':o.name,'actual_top_local_z_m':hit.z,'before_base_bottom_local_z_m':lo[2],'before_gap_m':gap,'vertical_translation_m':delta,'after_gap_m':newgap,'native_stand_vertices_moved':len(native_ids),'display_children_moved':[x.name for x in children],'unchanged':'desk,keyboard,otherprops,chair,materials,light/camera'})
assert len(rows)==6;bpy.context.view_layer.update();bpy.ops.wm.save_as_mainfile(filepath=str(out));assert hashlib.sha256(src.read_bytes()).hexdigest()==sha;(ref/'realism_refinement_r73.json').write_text(json.dumps({'source':str(src),'source_sha256':sha,'candidate':str(out),'trigger':'Full71 independent review monitor appearsfloating. Actual native base bottom0.814 vs table0.75 confirms64mm gap.','changes':rows,'photorealism_accepted':False,'requires':'Saved-source audits,evaluated support andsamecamera private/reverse views before adoption'},indent=2));print('Saved',out,flush=True)
