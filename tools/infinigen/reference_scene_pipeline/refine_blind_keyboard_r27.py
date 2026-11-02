"""Reject uniform key grid: real compact keyboard row widths and spacebar."""
import bpy,json,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];base=ROOT/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full';ref=ROOT/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';src=base/'scene_candidate_r26.blend';out=base/'scene_candidate_r27.blend';assert not out.exists();sha=hashlib.sha256(src.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(src));material=bpy.data.materials['BlindR1_keycap_ABS'];records=[]
for desk in list(bpy.data.objects):
 if not (desk.get('program_key','').startswith('private_') and desk.get('program_key','').endswith('_desk')):continue
 for o in list(bpy.data.objects):
  if o.parent==desk and o.name.startswith('BlindR1_key_'):bpy.data.objects.remove(o,do_unlink=True)
 rows=[[1]*13+[2],[1.5]+[1]*12+[1.5],[1.75]+[1]*11+[2.25],[2.25]+[1]*10+[2.75],[1.25,1.25,1.25,6.25,1,1,1,1,1,1]]
 # Unit total15. Row0 is farthest from user (+localX is user side).
 verts=[];faces=[];pat=[(-1,-1,-1),(1,-1,-1),(1,1,-1),(-1,1,-1),(-1,-1,1),(1,-1,1),(1,1,1),(-1,1,1)];fs=[(0,3,2,1),(4,5,6,7),(0,1,5,4),(1,2,6,5),(2,3,7,6),(3,0,4,7)]
 for row,widths in enumerate(rows):
  widths=[w*15/sum(widths) for w in widths];cursor=-.212
  for width in widths:
   W=width*.02825;center=(.022+row*.027,cursor+W/2,.7665);size=(.023,W-.003,.007);offset=len(verts);verts.extend([tuple(center[i]+sign[i]*size[i]/2 for i in range(3)) for sign in pat]);faces.extend([tuple(offset+i for i in face) for face in fs]);cursor+=W
 mesh=bpy.data.meshes.new('BlindR2_keyboard_mixed_key_widths');mesh.from_pydata(verts,[],faces);mesh.materials.append(material);o=bpy.data.objects.new('BlindR2_'+desk['program_key']+'_keyboard',mesh);bpy.context.scene.collection.objects.link(o);o.parent=desk;o['reference_scene_owner']='commercial_office_floor_02';o['program_key']=desk['program_key']+'_keyboard_keycaps';o['audit_kind']='detail';bev=o.modifiers.new('Moulded_key_edges','BEVEL');bev.width=.0009;bev.segments=3;o.modifiers.new('Keycap_planar_normals','WEIGHTED_NORMAL');records.append({'desk':desk['program_key'],'keycaps':len(faces)//6,'distinct_widths':True,'scope':'compact unlabelled keycaps with spacebar, shift, return and staggered row boundaries'})
bpy.ops.wm.save_as_mainfile(filepath=str(out));assert hashlib.sha256(src.read_bytes()).hexdigest()==sha;(ref/'realism_refinement_r27.json').write_text(json.dumps({'source':str(src),'candidate':str(out),'reason':'r26 direct visual review rejected uniform square grid as final keyboard appearance','changes':records,'photorealism_accepted':False},indent=2));print(records)
