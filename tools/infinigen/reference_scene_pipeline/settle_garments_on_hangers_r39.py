"""Physics support instead of air-pinned shoulders; six prototypes on actual wire-hanger colliders."""
import bpy,bmesh,math,json,hashlib,os
from pathlib import Path
from mathutils import Vector,Matrix
from mathutils.bvhtree import BVHTree
from detail_primitives import rod
ROOT=Path(__file__).resolve().parents[3];base=ROOT/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full';ref=ROOT/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';source=base/'scene_candidate_r37.blend';out=base/'scene_candidate_r39.blend';assert not out.exists();sha=hashlib.sha256(source.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(source));scene=bpy.context.scene;frame0=scene.frame_current;state=ref/'hanger_settlement_r39_job.json';state.write_text(json.dumps({'pid':os.getpid(),'phase':'preparing_hanger_contact','frames':60},indent=2));prototypes=[];colliders=[];origins=[];source_mats={};source_objects=[o for o in bpy.data.objects if '_native_garment_' in o.get('program_key','')]
for o in list(bpy.data.objects):
 if '_collar_band_' in o.get('program_key',''):bpy.data.objects.remove(o,do_unlink=True)
for i in range(6):
 original=next(o for o in source_objects if o.get('program_key')==f'101_native_garment_0_{i}');proto=original.copy();proto.data=original.data.copy();bpy.context.scene.collection.objects.link(proto);proto.parent=None;origin=Vector((i*2.0,0,2.0));proto.matrix_world=Matrix.Translation(origin);proto.name=f'Temporary_hanger_cloth_{i}'
 for mod in list(proto.modifiers):proto.modifiers.remove(mod)
 for v in proto.data.vertices:v.co.y+=.0008*math.sin(20*v.co.x+i)*math.sin(15*v.co.z)+.0004*math.cos(31*v.co.z-9*v.co.x+i)
 # Bake initial world positions for an independently supported cloth prototype.
 proto.data.transform(proto.matrix_world);proto.matrix_world=Matrix.Identity(4);origins.append(origin);prototypes.append(proto)
 parts=[]
 for j,(a,b) in enumerate([((-.18,0,-.075),(0,0,0)),((0,0,0),(.18,0,-.075)),((.18,0,-.075),(-.18,0,-.075))]):
  collider=rod(f'Temporary_wire_{i}_{j}',origin+Vector(a),origin+Vector(b),.0022,original.data.materials[0],segments=20);collider.modifiers.new('Fixed_wire_collision','COLLISION');collider.collision.thickness_outer=.001;collider.collision.cloth_friction=2.5;parts.append(collider);colliders.append(collider)
 cm=proto.modifiers.new('Gravity_on_actual_hanger','CLOTH');s=cm.settings;s.quality=12;s.mass=.18;s.tension_stiffness=25;s.compression_stiffness=25;s.shear_stiffness=12;s.bending_stiffness=.65;s.air_damping=4;c=cm.collision_settings;c.use_collision=True;c.distance_min=.0015;c.collision_quality=8;c.use_self_collision=True;c.self_distance_min=.001;c.self_friction=1;cm.point_cache.frame_start=1;cm.point_cache.frame_end=60
 band=proto.vertex_groups.new(name='Reinforced_neck_binding')
 for v in proto.data.vertices:
  q=v.co-origin
  if abs(q.x)<.14 and q.z>-.14:band.add([v.index],min(1,max(0,(q.z+.14)/.07)), 'REPLACE')
 s.vertex_group_bending=band.name;s.bending_stiffness_max=3.0
for frame in range(1,61):
 scene.frame_set(frame)
 if frame%5==0:state.write_text(json.dumps({'pid':os.getpid(),'phase':'simulating_actual_hanger_contact','frame':frame,'frames':60,'prototypes':6},indent=2));print('HANGER_PHYSICS_FRAME',frame,flush=True)
proof=[]
for i,proto in enumerate(prototypes):
 bpy.ops.object.select_all(action='DESELECT');bpy.context.view_layer.objects.active=proto;proto.select_set(True);bpy.ops.object.modifier_apply(modifier='Gravity_on_actual_hanger');origin=origins[i]
 for v in proto.data.vertices:v.co-=origin
 lo=[min(v.co[k] for v in proto.data.vertices) for k in range(3)];hi=[max(v.co[k] for v in proto.data.vertices) for k in range(3)];assert -.20<hi[2]<.05 and lo[2]>-.9,('not supported by hanger',i,lo,hi)
 verts=[];faces=[]
 for collider in colliders[i*3:i*3+3]:
  offset=len(verts);verts.extend([v.co-origin for v in collider.data.vertices]);faces.extend([tuple(offset+v for v in f.vertices) for f in collider.data.polygons])
 tree=BVHTree.FromPolygons(verts,faces);gap=min(tree.find_nearest(v.co)[3] for v in proto.data.vertices if v.co.z>-.2);assert gap<.009,('no hanger contact',i,gap);proof.append({'pattern':i,'hanger_contact_gap_m':gap,'hanger_relative_bounds':[lo,hi]})
for o in source_objects:
 unit,_,_,tier,g=o['program_key'].split('_');i=(int(g)+2*int(tier)+(int(unit)-101)*3)%6;mat=o.data.materials[0];o.data=prototypes[i].data.copy();o.data.materials.clear();o.data.materials.append(mat);o['hanger_contact_drape_frames']=60
 rot=Matrix.Rotation(o.rotation_euler.z,4,'Z');pts=[rot@v.co+o.location for v in o.data.vertices];lo=min(p.y for p in pts);hi=max(p.y for p in pts);delta=max(0,-1.19-lo) if lo< -1.20 else min(0,.29-hi) if hi>.30 else 0
 if delta:
  o.location.y+=delta
  for kind in ['hanger','hook']:
   part=next(x for x in bpy.data.objects if x.get('program_key')==f'{unit}_{kind}_{tier}_{g}');part.location.y+=delta
for o in prototypes+colliders:bpy.data.objects.remove(o,do_unlink=True)
scene.frame_set(frame0);bpy.context.view_layer.update();bpy.ops.wm.save_as_mainfile(filepath=str(out));assert hashlib.sha256(source.read_bytes()).hexdigest()==sha;(ref/'realism_refinement_r39.json').write_text(json.dumps({'source':str(source),'candidate':str(out),'source_sha256':sha,'trigger':'Independent r37: shoulders air-pinned above hanger,flat panels and missing hem/cuff sewing','change':'free cloth under gravity supported by true2.2mm wire triangles,60-frame self-collision,native-like .65 bending with locally reinforced neck3.0,max tension25 and reduced friction; r38 low-bending crumpling rejected;previous collar bands removed pending evaluated-surface regeneration','prototype_contacts':proof,'photorealism_accepted':False,'requires':['new collar/hem/cuff bands on evaluated settled surface','support/frame audit','same-camera image and independent review']},indent=2));state.write_text(json.dumps({'pid':os.getpid(),'phase':'supported_prototypes_baked','candidate':str(out),'photorealism_accepted':False},indent=2));print('SAVED',out,flush=True)
