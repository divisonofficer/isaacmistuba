"""Fit native wardrobe clothes within side panels and seat folded stacks on shelf tops."""
import bpy,bmesh,json
from pathlib import Path
R=Path(__file__).resolve().parents[3];F=R/'out/infinigen_v2/kr_pivotHouse_48712501/full';B=R/'data/venue_refs/floor_plans_v3/pivot_courtyard_house_01';o=next(o for o in bpy.data.objects if o.name.startswith('OpenWardrobeFactory'));bm=bmesh.new();bm.from_mesh(o.data);seen=set();changes=[];outside=[]
for v in bm.verts:
 if v in seen:continue
 seen.add(v);todo=[v];c=[]
 while todo:
  p=todo.pop();c.append(p)
  for e in p.link_edges:
   q=e.other_vert(p)
   if q not in seen:seen.add(q);todo.append(q)
 slots={f.material_index for v in c for f in v.link_faces}
 if not slots or min(slots)<3:continue
 lo=[min(v.co[k] for v in c) for k in range(3)];hi=[max(v.co[k] for v in c) for k in range(3)];dy=0.;dz=0.
 if lo[1]<-1.145:dy=-1.145-lo[1]
 if hi[1]+dy>1.145:dy=1.145-hi[1]
 if lo[1]>.315 and len(c)==8:
  # Original loop produced third stack with y_max1.26 through panel y1.17.
  shelf=min((.45,.90,1.35,1.80),key=lambda z:abs(z-lo[2]));dz=shelf+.0125+.003-lo[2]
 if abs(dy)>1e-6 or abs(dz)>1e-6:
  for p in c:p.co.y+=dy;p.co.z+=dz
  changes.append({'slots':list(slots),'before_lo':lo,'before_hi':hi,'translate_yz':[dy,dz]})
 if min(v.co.y for v in c)<-1.14501 or max(v.co.y for v in c)>1.14501:outside.append(list(slots))
assert not outside,outside
bm.to_mesh(o.data);bm.free();o.data.update();bpy.context.scene['pivot_revision']='r20_wardrobe_contact';bpy.ops.wm.save_as_mainfile(filepath=str(F/'scene_review_r20.blend'))
(B/'revision_r20.json').write_text(json.dumps({'object':o.name,'component_changes':changes,'clothes_outside_side_panels_after':outside,'source_issue':'Native folded stack loop allowed y_max1.26 through side panel inner boundary1.17; some folded bottoms intersected shelf tops.','other_meshes_changed':False},indent=2));print('PIVOT_R20_COMPLETE',len(changes),flush=True)
