"""Keep cylindrical side normals separate from caps; avoid false curved reflections."""
import bpy,bmesh,math,json,hashlib
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];base=ROOT/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full';source=base/'scene_candidate_r21.blend';out=base/'scene_candidate_r22.blend';assert not out.exists();before=hashlib.sha256(source.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(source));o=next(o for o in bpy.data.objects if o.get('program_key')=='coffee_machine_carafe');bm=bmesh.new();bm.from_mesh(o.data)
for f in bm.faces:f.smooth=abs(f.normal.z)<.8
for e in bm.edges:e.smooth=len(e.link_faces)==2 and e.calc_face_angle(0)<math.radians(35)
bm.to_mesh(o.data);bm.free();o.data.update();mod=o.modifiers.new('rolled_pitcher_rim','BEVEL');mod.width=.00035;mod.segments=3;mod.limit_method='ANGLE';mod.angle_limit=math.radians(40)
bpy.ops.wm.save_as_mainfile(filepath=str(out));assert hashlib.sha256(source.read_bytes()).hexdigest()==before
ref=ROOT/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';(ref/'realism_refinement_r22.json').write_text(json.dumps({'source':str(source),'candidate':str(out),'cause':'Smooth normals were averaged between large caps and cylinder side, giving false broad curvature to specular reflections.','change':'Sharp cap boundaries, smooth cylindrical sides,0.35mm rolled rim bevel; previous PBR UV brush retained.','photorealism_accepted':False},indent=2))
