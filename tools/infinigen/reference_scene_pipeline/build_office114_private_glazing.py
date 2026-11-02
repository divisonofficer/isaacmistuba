"""Six native full-height glazing trials; preserve source and require matched visual review."""
import bpy,bmesh,json,math,hashlib,sys
from pathlib import Path
from mathutils import Vector,Matrix
r=Path(__file__).resolve().parents[3];d=r/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';base=r/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full';src=base/'scene_candidate_r113_draft.blend';dst=base/'scene_candidate_r114_draft.blend';assert not dst.exists();a=json.loads((d/'private_windows114_source_probe.json').read_text());bpy.ops.wm.open_mainfile(filepath=str(src));asset=d/'native_private_glazing114/asset.blend'
with bpy.data.libraries.load(str(asset),link=False) as (s,z):z.objects=['Office02_native_private_glazing114']
proto=z.objects[0];bpy.context.scene.collection.objects.link(proto);bpy.context.view_layer.update();native=proto.data.copy();native.transform(proto.matrix_world);rows=[]
def cut(o,pose):
 bm=bmesh.new();bm.from_mesh(o.data);to_local=pose.inverted()@o.matrix_world;bmesh.ops.transform(bm,matrix=to_local,verts=list(bm.verts));lo=(-1.05,-.4,.0225);hi=(1.05,.4,2.3725)
 for k in range(3):
  for v in (lo[k],hi[k]):
   p=[0.,0.,0.];p[k]=v;n=[0.,0.,0.];n[k]=1;bmesh.ops.bisect_plane(bm,geom=list(bm.verts)+list(bm.edges)+list(bm.faces),dist=1e-6,plane_co=Vector(p),plane_no=Vector(n))
 fs=[f for f in bm.faces if all(lo[k]+1e-5<f.calc_center_median()[k]<hi[k]-1e-5 for k in range(3))];n=len(fs)
 if fs:bmesh.ops.delete(bm,geom=fs,context='FACES')
 bmesh.ops.transform(bm,matrix=to_local.inverted(),verts=list(bm.verts));o.data=o.data.copy();bm.to_mesh(o.data);bm.free();o.data.update();return n
for row in a['rooms']:
 cy=sum(p[1] for p in row['polygon'])/len(row['polygon']);pose=Matrix.Translation(Vector((.045*cy+.055,cy,.169)))@Matrix.Rotation(math.atan2(1,.045),4,'Z');cuts=[]
 for suffix in ['.wall','.exterior','','.meshed']:
  o=bpy.data.objects.get(row['room_id']+suffix)
  if o and o.type=='MESH':cuts.append({'object':o.name,'removed_faces':cut(o,pose),'hide_render':o.hide_render})
 removed=[]
 for w in row['windows']:
  old=bpy.data.objects[w['object']];parent=old.parent;targets=list(parent.children_recursive)+[parent] if parent else list(old.children_recursive)+[old]
  for o in targets:
   if o.name in bpy.data.objects:removed.append({'name':o.name,'type':o.type});bpy.data.objects.remove(o,do_unlink=True)
 o=bpy.data.objects.new('Office114_fullheight_'+row['room'],native.copy());bpy.context.scene.collection.objects.link(o);o.matrix_world=pose;o['program_key']=row['room']+'_fullheight_window114';o['reference_scene_owner']='commercial_office_floor_02';rows.append({'room':row['room'],'object':o.name,'pose':[list(v) for v in pose],'cuts':cuts,'removed':removed,'unit_scale':list(o.scale),'aperture_local_bounds':[[-1.05,-.4,.0225],[1.05,.4,2.3725]]})
bpy.data.objects.remove(proto,do_unlink=True);bpy.context.view_layer.update();bpy.ops.wm.save_as_mainfile(filepath=str(dst));out={'source':str(src),'candidate':str(dst),'source_sha256':hashlib.sha256(src.read_bytes()).hexdigest(),'candidate_sha256':hashlib.sha256(dst.read_bytes()).hexdigest(),'native_asset_sha256':hashlib.sha256(asset.read_bytes()).hexdigest(),'rooms':rows,'scope':'Native unscaled 2.145x0.22x2.395m windows. Enlarged apertures in native wall layers; removed old window assemblies and their six portal lights. Lighting change is part of aperture trial. Reveal fit, RGB, exterior reference, global navigation remain unaccepted.','accepted':False};(d/'glazing114_build.json').write_text(json.dumps(out,indent=2));print('OFFICE114_SAVED')
