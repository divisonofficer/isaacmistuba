"""Blind-review correction: explicit dielectric electronics and physical keyboard caps."""
import bpy,bmesh,json,hashlib
from pathlib import Path
from material_detail import material
ROOT=Path(__file__).resolve().parents[3];base=ROOT/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full';ref=ROOT/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';source=base/'scene_candidate_r24.blend';out=base/'scene_candidate_r26.blend';assert not out.exists();sha=hashlib.sha256(source.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(source))
def mat(n,c,r):return material(n,c,r)[0]
plastic=mat('BlindR1_electronics_ABS',(.018,.020,.024),.36);keys=mat('BlindR1_keycap_ABS',(.055,.060,.067),.49);screen=mat('BlindR1_display_glass',(.009,.014,.021),.13)
records=[]
def box(parent,name,center,size,m,bevel=.0008):
 bpy.ops.mesh.primitive_cube_add(size=1);o=bpy.context.object;o.name='BlindR1_'+name;o.parent=parent;o.location=center;o.scale=size;bpy.ops.object.transform_apply(location=False,rotation=False,scale=True);o.data.materials.append(m);mod=o.modifiers.new('Manufactured_edge','BEVEL');mod.width=bevel;mod.segments=3;o.modifiers.new('Planar_normals','WEIGHTED_NORMAL');o['reference_scene_owner']='commercial_office_floor_02';o['program_key']=parent['program_key']+'_'+name;o['audit_kind']='detail';return o
for o in list(bpy.data.objects):
 key=o.get('program_key','')
 if not (key.startswith('private_') and key.endswith('_desk')):continue
 # Replace all electronics' shared metallic/woodlike material; preserve actual timber desk parts.
 for i,m in enumerate(o.data.materials):
  if m and ('black_metal' in m.name or 'screen' in m.name):o.data.materials[i]=plastic
 # Delete only disconnected monitor body/screen boxes, retain stand and desk.
 bm=bmesh.new();bm.from_mesh(o.data);pending=set(bm.verts);centers=[];remove=[]
 while pending:
  stack=[pending.pop()];comp=set(stack)
  while stack:
   v=stack.pop()
   for e in v.link_edges:
    w=e.other_vert(v)
    if w in pending:pending.remove(w);comp.add(w);stack.append(w)
  lo=[min(v.co[i] for v in comp) for i in range(3)];hi=[max(v.co[i] for v in comp) for i in range(3)]
  if lo[2]>.89 and hi[1]-lo[1]>.5:
   if hi[1]-lo[1]<.57:centers.append(((lo[0]+hi[0])/2,(lo[1]+hi[1])/2,(lo[2]+hi[2])/2))
   remove.extend(comp)
 bmesh.ops.delete(bm,geom=remove,context='VERTS');bm.to_mesh(o.data);bm.free()
 for j,(x,y,z) in enumerate(centers):
  box(o,f'monitor_{j}_housing',(x,y,z),(.026,.58,.35),plastic,.002)
  box(o,f'monitor_{j}_active_glass',(x+.014,y,z+.003),(.0012,.552,.316),screen,.0005)
  box(o,f'monitor_{j}_power_button',(x+.015,y+.255,z-.158),(.002,.008,.003),keys,.0005)
 for row in range(5):
  for col in range(15):
   box(o,f'key_{row}_{col}',(.022+row*.027,-.199+col*.0284,.7665),(.023,.024,.007),keys,.001)
 records.append({'desk':key,'monitors':len(centers),'keycaps':75,'materials':'dielectric ABS housing/keycaps and dark display glass; no wood mapping','screen_faces_user_side':'+localX'})
bpy.ops.wm.save_as_mainfile(filepath=str(out));assert hashlib.sha256(source.read_bytes()).hexdigest()==sha
(ref/'realism_refinement_r26.json').write_text(json.dumps({'source':str(source),'source_sha256':sha,'candidate':str(out),'blind_review_trigger':'Monitor and keyboard read as striped timber slabs','changes':records,'photorealism_accepted':False},indent=2));print(records,flush=True)
