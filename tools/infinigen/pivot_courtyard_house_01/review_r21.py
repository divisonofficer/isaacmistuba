"""Resolve r20's folded-stack overlap by fitting all three columns together."""
import bpy,bmesh,json
from pathlib import Path
R=Path(__file__).resolve().parents[3];F=R/'out/infinigen_v2/kr_pivotHouse_48712501/full';B=R/'data/venue_refs/floor_plans_v3/pivot_courtyard_house_01';o=next(o for o in bpy.data.objects if o.name.startswith('OpenWardrobeFactory'));bm=bmesh.new();bm.from_mesh(o.data);seen=set();shelves={k:[] for k in range(4)}
for v in bm.verts:
 if v in seen:continue
 todo=[v];seen.add(v);c=[]
 while todo:
  p=todo.pop();c.append(p)
  for e in p.link_edges:
   q=e.other_vert(p)
   if q not in seen:seen.add(q);todo.append(q)
 slots={f.material_index for v in c for f in v.link_faces};lo=[min(v.co[k] for v in c) for k in range(3)];hi=[max(v.co[k] for v in c) for k in range(3)]
 if slots and min(slots)>=3 and len(c)==8 and lo[1]>.315:
  level=min(range(4),key=lambda k:abs((.45,.9,1.35,1.8)[k]+.0155-lo[2]));shelves[level].append(c)
changes=[];audits=[]
for level,groups in shelves.items():
 assert len(groups)==3,(level,len(groups))
 groups.sort(key=lambda c:sum(v.co.y for v in c)/len(c));boxes=[]
 for i,c in enumerate(groups):
  lo=min(v.co.y for v in c);hi=max(v.co.y for v in c);mid=(lo+hi)/2;target=(.47,.74,1.01)[i]
  for v in c:v.co.y=target+(v.co.y-mid)*(.25/(hi-lo))
  bounds=[(min(v.co[k] for v in c),max(v.co[k] for v in c)) for k in range(3)];boxes.append(bounds);changes.append({'level':level,'column':i,'bounds':bounds})
 for i in range(2):assert boxes[i][1][1]+.019<boxes[i+1][1][0],boxes
 audits.append({'level':level,'y_gaps':[boxes[i+1][1][0]-boxes[i][1][1] for i in range(2)],'outside_panel':any(x[1][0]<.33 or x[1][1]>1.145 for x in boxes)})
assert not any(a['outside_panel'] for a in audits)
bm.to_mesh(o.data);bm.free();o.data.update();bpy.context.scene['pivot_revision']='r21_wardrobe_columns';bpy.ops.wm.save_as_mainfile(filepath=str(F/'scene_review_r21.blend'))
(B/'revision_r21.json').write_text(json.dumps({'regression':'r20 clamp fixed side penetration but overlapped third stack with middle stack.','changes':changes,'shelf_pairwise_audits':audits,'other_meshes_changed':False},indent=2));print('PIVOT_R21_COMPLETE',flush=True)
