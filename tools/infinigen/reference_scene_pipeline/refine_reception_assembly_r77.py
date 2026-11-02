"""Measured reception panel overlap and54mm floating monitor assembly correction;no material/light edits."""
import bpy,json,hashlib
from pathlib import Path
r=Path('/jarvis/project/robomituba');base=r/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full';ref=r/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';src=base/'scene_candidate_r76.blend';out=base/'scene_candidate_r77.blend';assert not out.exists();sha=hashlib.sha256(src.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(src));parents=[o for o in bpy.data.objects if o.type=='MESH' and 'ReceptionDeskFactory' in o.name];assert len(parents)==1;o=parents[0];me=o.data;graph={v.index:set() for v in me.vertices}
for e in me.edges:
 a,b=e.vertices;graph[a].add(b);graph[b].add(a)
components=[]
while graph:
 todo=[next(iter(graph))];seen=set()
 while todo:
  i=todo.pop()
  if i in seen:continue
  seen.add(i);todo.extend(graph.get(i,set())-seen)
 for i in seen:graph.pop(i,None)
 vs=[me.vertices[i].co for i in seen];lo=[min(v[k] for v in vs) for k in range(3)];hi=[max(v[k] for v in vs) for k in range(3)];mats={p.material_index for p in me.polygons if all(i in seen for i in p.vertices)};components.append((seen,lo,hi,mats))
assert len(components)==9
sides=[c for c in components if c[3]=={0} and abs(c[2][2]-.74)<1e-5];assert len(sides)==2
front=next(c for c in components if c[3]=={0} and abs(c[2][2]-1.1)<1e-5)
monitor=[c for c in components if c[3] in [{3},{4}]];assert len(monitor)==4 and sum(len(c[0]) for c in monitor)==32
work=next(c for c in components if c[3]=={2});stand=next(c for c in monitor if abs((c[2][2]-c[1][2])-.012)<1e-5);dz=work[2][2]-stand[1][2];assert abs(dz+.054)<1e-5
changed={i for c in monitor for i in c[0]}|{i for c in sides for i in c[0] if me.vertices[i].co.x>.32};before=[tuple(v.co) for v in me.vertices];polys=[(tuple(p.vertices),p.material_index,p.use_smooth) for p in me.polygons]
for c in sides:
 for i in c[0]:
  if me.vertices[i].co.x>.32:me.vertices[i].co.x=front[1][0]-.002
for c in monitor:
 for i in c[0]:me.vertices[i].co.z+=dz
me.update();assert all(tuple(v.co)==before[v.index] for v in me.vertices if v.index not in changed);assert polys==[(tuple(p.vertices),p.material_index,p.use_smooth) for p in me.polygons]
base_bottom=min(me.vertices[i].co.z for i in stand[0]);assert abs(base_bottom-work[2][2])<1e-6
for c in sides:assert abs(front[1][0]-max(me.vertices[i].co.x for i in c[0])-.002)<1e-6
bpy.context.view_layer.update();bpy.ops.wm.save_as_mainfile(filepath=str(out));assert hashlib.sha256(src.read_bytes()).hexdigest()==sha;(ref/'realism_refinement_r77.json').write_text(json.dumps({'source':str(src),'source_sha256':sha,'candidate':str(out),'object':o.name,'old_side_front_overlap_x_m':.02,'new_side_front_gap_m':.002,'monitor_translation_z_m':dz,'monitor_base_bottom_after_m':base_bottom,'worktop_top_m':work[2][2],'unchanged_other_vertex_count':len(before)-len(changed),'changed_vertex_count':len(changed),'all_polygon_indices_materials_smoothing_preserved':True,'photorealism_accepted':False,'hypothesis':'Coplanar overlapping native front/side faces mayexplain black corner;test physical buttjoin with2mm reveal. Monitor gap isdirectly measured.','requires':'saved four audits,same-camera reception A/B plusfresh independent review;not whole-scene acceptance'},indent=2));print('Saved',out,flush=True)
