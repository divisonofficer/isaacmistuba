"""Actual rear stiles and seat apron transfer the upholstered chair back to the legs."""
import bpy,bmesh,json,hashlib
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree
ROOT=Path(__file__).resolve().parents[3];base=ROOT/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full';ref=ROOT/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';src=base/'scene_candidate_r44.blend';out=base/'scene_candidate_r45.blend';assert not out.exists();sha=hashlib.sha256(src.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(src));rows=[]
def tree(o):return BVHTree.FromPolygons([v.co.copy() for v in o.data.vertices],[list(f.vertices) for f in o.data.polygons])
def beam(parent,key,stations,width,depth,mat):
 verts=[]
 for x,y,z in stations:
  verts += [(x-depth/2,y-width/2,z),(x+depth/2,y-width/2,z),(x+depth/2,y+width/2,z),(x-depth/2,y+width/2,z)]
 faces=[(3,2,1,0)]
 for j in range(len(stations)-1):
  for k in range(4):faces.append((4*j+k,4*j+(k+1)%4,4*(j+1)+(k+1)%4,4*(j+1)+k))
 n=4*(len(stations)-1);faces.append((n,n+1,n+2,n+3));mesh=bpy.data.meshes.new(key);mesh.from_pydata(verts,[],faces);mesh.materials.append(mat)
 uv=mesh.uv_layers.new(name='UVMap')
 for f in mesh.polygons:
  for li in f.loop_indices:
   q=mesh.vertices[mesh.loops[li].vertex_index].co;uv.data[li].uv=(q.y*4+q.x*3,q.z*2)
 o=bpy.data.objects.new('BreakoutR45_'+key,mesh);bpy.context.scene.collection.objects.link(o);o.parent=parent;o['program_key']=key;o['reference_scene_owner']='commercial_office_floor_02';o['audit_kind']='detail';mod=o.modifiers.new('Manufactured edge radius','BEVEL');mod.width=.0015;mod.segments=3;return o
for parent in list(bpy.data.objects):
 key=parent.get('program_key','')
 if parent.type!='MESH' or not key.startswith('breakout_chair') or parent.parent is not None:continue
 mat=next(m for m in parent.data.materials if m and 'oak' in m.name);back=next(o for o in bpy.data.objects if o.get('program_key')==key+'_back_upholstery');backtree=tree(back);legtree=tree(parent);supports=[]
 for side,sign in enumerate([-1,1]):
  # Starts within the existing rear leg and passes behind the lower upholstered back.
  stations=[(-.20,sign*.20,.37),(-.20,sign*.20,.43),(-.20,sign*.185,.49),(-.20,sign*.165,.55),(-.20,sign*.15,.61),(-.20,sign*.145,.67)]
  o=beam(parent,key+f'_rear_stile_{side}',stations,.032,.032,mat);t=tree(o);contacts={'existing_leg_surface_pairs':len(t.overlap(legtree)),'back_surface_pairs':len(t.overlap(backtree))};assert contacts['existing_leg_surface_pairs']>0 and contacts['back_surface_pairs']>0,contacts;supports.append({'object':o.name,'section_m':[.032,.032],'stations':stations,'surface_intersections':contacts,'note':'Intentional embedded join,not free-standing or continuous load simulation.'})
 # Rear apron connects both rear legs below the cushion.
 bm=bmesh.new();bmesh.ops.create_cube(bm,size=1);bmesh.ops.scale(bm,vec=Vector((.034,.40,.05)),verts=bm.verts);bmesh.ops.translate(bm,vec=Vector((-.19,0,.405)),verts=bm.verts);mesh=bpy.data.meshes.new(key+'_rear_apron');bm.to_mesh(mesh);bm.free();mesh.materials.append(mat);o=bpy.data.objects.new('BreakoutR45_rear_apron',mesh);bpy.context.scene.collection.objects.link(o);o.parent=parent;o['program_key']=key+'_rear_apron';o['reference_scene_owner']='commercial_office_floor_02';o['audit_kind']='detail';mod=o.modifiers.new('Apron edge radius','BEVEL');mod.width=.0015;mod.segments=3
 rows.append({'chair':key,'rear_stiles':supports,'rear_apron_dimensions_m':[.034,.40,.05],'preserved':'upholstery,seat,legs,room transforms,materials andlighting'})
assert len(rows)==4;bpy.context.view_layer.update();bpy.ops.wm.save_as_mainfile(filepath=str(out));assert hashlib.sha256(src.read_bytes()).hexdigest()==sha;(ref/'realism_refinement_r45.json').write_text(json.dumps({'source':str(src),'source_sha256':sha,'candidate':str(out),'trigger':'Fresh image-only review44:back-to-seat load path unreadable','changes':rows,'photorealism_accepted':False,'requires':'actual front/rear close renders,clearance andwhole source regression;embedded joint not structural engineering certification'},indent=2));print('SAVED',out,flush=True)
