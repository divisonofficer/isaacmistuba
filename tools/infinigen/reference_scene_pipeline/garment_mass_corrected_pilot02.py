"""Single fresh ShirtFactory trial: correct Blender mass per vertex; no integration.
Derived from supported-hanger r41 setup, retains collider/contact constraints.
Previous r41 used 0.18kg per vertex; this trial uses 0.18kg total.
Trial02 varies bending stiffness only, 0.65 to5.0, against01; adds relative extent rejection.
"""
import bpy,bmesh,math,json,hashlib,os,bisect,sys
from pathlib import Path
from mathutils import Vector,Matrix
from mathutils.bvhtree import BVHTree
from detail_primitives import rod
ROOT=Path(__file__).resolve().parents[3];base=ROOT/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full';ref=ROOT/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';source=base/'scene_candidate_r37.blend';out=ref/'garment_mass_corrected_pilot02.blend';assert not out.exists();sha=hashlib.sha256(source.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(source));scene=bpy.context.scene;frame0=scene.frame_current;state=ref/'garment_mass_corrected_pilot02_job.json';state.write_text(json.dumps({'pid':os.getpid(),'phase':'preparing_hanger_contact','frames':60},indent=2));prototypes=[];colliders=[];origins=[];source_mats={};source_objects=[o for o in bpy.data.objects if '_native_garment_' in o.get('program_key','')]
for o in list(bpy.data.objects):
 if '_collar_band_' in o.get('program_key',''):bpy.data.objects.remove(o,do_unlink=True)
sys.path[:0]=[str(ROOT/'tools/infinigen'),str(ROOT/'modules/infinigen')]
from room_planner import proc_assets as pa
fresh=[]
for i in range(1):
 attrs={'width':[.40,.42,.39,.43,.41,.40][i],'size':[.51,.55,.50,.57,.53,.56][i],'size_neck':[.025,.032,.028,.030,.026,.035][i],'sleeve_width':.095 if i<4 else .105,'sleeve_length':.09 if i<4 else .23,'sleeve_angle':.60,'thickness':.022}
 f=pa._cloth('shirt','ShirtFactory',811330+i,**attrs);assert f is not None
 f.data.transform(Matrix.Rotation(math.pi/2,4,'X'));bpy.context.view_layer.objects.active=f;f.select_set(True)
 md=f.modifiers.new('Factory_mesh_reduction','DECIMATE');md.ratio=.3;bpy.ops.object.modifier_apply(modifier=md.name)
 bounds=[(min(v.co[k] for v in f.data.vertices),max(v.co[k] for v in f.data.vertices)) for k in range(3)];scale=min(1,.47/(bounds[0][1]-bounds[0][0]),.59/(bounds[2][1]-bounds[2][0]));cx=sum(bounds[0])/2;cy=sum(bounds[1])/2;top=bounds[2][1]
 for v in f.data.vertices:v.co=Vector(((v.co.x-cx)*scale,(v.co.y-cy)*scale,(v.co.z-top)*scale))
 bm=bmesh.new();bm.from_mesh(f.data);remove=[]
 for face in bm.faces:
  c=face.calc_center_median();depth=.065 if c.y<0 else .035
  if abs(c.x)<.102 and c.z> -depth*math.sqrt(max(0,1-(c.x/.102)**2)):remove.append(face)
 bmesh.ops.delete(bm,geom=remove,context='FACES');loose=[v for v in bm.verts if not v.link_faces]
 if loose:bmesh.ops.delete(bm,geom=loose,context='VERTS')
 bm.to_mesh(f.data);bm.free();fresh.append(f)
for i in range(1):
 original=next(o for o in source_objects if o.get('program_key')==f'101_native_garment_0_{i}');proto=original.copy();proto.data=fresh[i].data.copy();bpy.context.scene.collection.objects.link(proto);proto.parent=None;origin=Vector((i*2.0,0,2.0));proto.matrix_world=Matrix.Translation(origin);proto.name=f'Temporary_hanger_cloth_{i}'
 for mod in list(proto.modifiers):proto.modifiers.remove(mod)
 for v in proto.data.vertices:v.co.y+=.0008*math.sin(20*v.co.x+i)*math.sin(15*v.co.z)+.0004*math.cos(31*v.co.z-9*v.co.x+i)
 # Place shoulder region near the real wire, preserving chest/neck geometry below.
 upper_pairs=sorted((abs(v.co.x),v.co.z) for v in proto.data.vertices if v.co.z>-.16);upper_keys=[x for x,z in upper_pairs]
 for v in proto.data.vertices:
  q=v.co;ax=abs(q.x)
  if .07<ax<.21 and q.z>-.24:
   candidates=[z for x,z in upper_pairs[bisect.bisect_right(upper_keys,ax-.012):bisect.bisect_left(upper_keys,ax+.012)]]
   if candidates:
    native_top=max(candidates);wire_z=-.075*min(ax/.18,1);shift=min(0,wire_z+.004-native_top);blend=min(1,max(0,(q.z+.24)/.12));q.z+=shift*blend
 # Bake initial world positions for an independently supported cloth prototype.
 proto.data.transform(proto.matrix_world);proto.matrix_world=Matrix.Identity(4);origins.append(origin);prototypes.append(proto)
 parts=[]
 for j,(a,b) in enumerate([((-.18,0,-.075),(0,0,0)),((0,0,0),(.18,0,-.075)),((.18,0,-.075),(-.18,0,-.075))]):
  collider=rod(f'Temporary_wire_{i}_{j}',origin+Vector(a),origin+Vector(b),.0022,original.data.materials[0],segments=20);collider.modifiers.new('Fixed_wire_collision','COLLISION');collider.collision.thickness_outer=.001;collider.collision.cloth_friction=2.5;parts.append(collider);colliders.append(collider)
 cm=proto.modifiers.new('Gravity_on_actual_hanger','CLOTH');s=cm.settings;s.quality=12;s.mass=.18/len(proto.data.vertices);s.tension_stiffness=25;s.compression_stiffness=25;s.shear_stiffness=12;s.bending_stiffness=5.0;s.air_damping=4;c=cm.collision_settings;c.use_collision=True;c.distance_min=.0015;c.collision_quality=8;c.use_self_collision=True;c.self_distance_min=.001;c.self_friction=1;cm.point_cache.frame_start=1;cm.point_cache.frame_end=60
 band=proto.vertex_groups.new(name='Reinforced_neck_binding')
 for v in proto.data.vertices:
  q=v.co-origin
  if abs(q.x)<.14 and q.z>-.14:band.add([v.index],min(1,max(0,(q.z+.14)/.07)), 'REPLACE')
 s.vertex_group_bending=band.name;s.bending_stiffness_max=3.0
 pins=proto.vertex_groups.new(name='Supported_shoulder_contacts');pin_proof=[]
 for side in [-1,1]:
  a=Vector((side*.18,0,-.075));b=Vector((0,0,0));axis=(b-a).normalized();eligible=[]
  for v in proto.data.vertices:
   q=v.co-origin
   if not (.12<side*q.x<.19 and q.z>-.13):continue
   t=max(0,min((q-a).dot(axis),(b-a).length));center=a+axis*t;radial=Vector((0,.5 if q.y>=0 else -.5,1));radial-=axis*radial.dot(axis);target=center+radial.normalized()*(.0022+.0015);distance=(q-target).length
   if distance<=.014:eligible.append((distance,v,target))
  chosen=[]
  for sign in [-1,1]:
   candidates=sorted([r for r in eligible if sign*(r[1].co.y-origin.y)>=0],key=lambda r:r[0]+.1*abs(abs(r[1].co.x-origin.x)-.16));assert len(candidates)>=3,('insufficient true shoulder contact',i,side,sign,len(candidates));chosen+=candidates[:3]
  for distance,v,q in chosen:
   v.co=origin+q;pins.add([v.index],1,'REPLACE');pin_proof.append({'vertex':v.index,'initial_snap_m':distance,'target_local':list(q),'side':side})
 proto['initial_extent_json']=json.dumps([max(v.co[k] for v in proto.data.vertices)-min(v.co[k] for v in proto.data.vertices) for k in range(3)])
 proto['actual_total_mass_kg']=float(s.mass)*len(proto.data.vertices)
 proto['contact_pin_proof_json']=json.dumps(pin_proof)
 s.vertex_group_mass=pins.name;proto['supported_contact_pin_count']=len(pin_proof)

for frame in range(1,61):
 scene.frame_set(frame)
 if frame%5==0:state.write_text(json.dumps({'pid':os.getpid(),'phase':'simulating_actual_hanger_contact','frame':frame,'frames':60,'prototypes':1},indent=2));print('HANGER_PHYSICS_FRAME',frame,flush=True)
proof=[]
for i,proto in enumerate(prototypes):
 bpy.ops.object.select_all(action='DESELECT');bpy.context.view_layer.objects.active=proto;proto.select_set(True);bpy.ops.object.modifier_apply(modifier='Gravity_on_actual_hanger');origin=origins[i]
 for v in proto.data.vertices:v.co-=origin
 lo=[min(v.co[k] for v in proto.data.vertices) for k in range(3)];hi=[max(v.co[k] for v in proto.data.vertices) for k in range(3)];assert -.20<hi[2]<.05 and lo[2]>-.9,('not supported by hanger',i,lo,hi)
 initial=json.loads(proto['initial_extent_json']);final=[hi[k]-lo[k] for k in range(3)];height_ratio=final[2]/initial[2];width_ratio=final[0]/initial[0]
 if height_ratio<.70 or width_ratio<.70:
  state.write_text(json.dumps({'pid':os.getpid(),'phase':'rejected_shape_collapse_before_rgb','initial_extents_m':initial,'final_extents_m':final,'height_ratio':height_ratio,'width_ratio':width_ratio,'actual_total_mass_kg':proto['actual_total_mass_kg'],'bending_stiffness':5.0,'reason':'less than70percent initial height or width; not a realism pass','photorealism_accepted':False},indent=2))
  raise RuntimeError('Garment extent collapsed; no render or integration')
 verts=[];faces=[]
 for collider in colliders[i*3:i*3+3]:
  offset=len(verts);verts.extend([v.co-origin for v in collider.data.vertices]);faces.extend([tuple(offset+v for v in f.vertices) for f in collider.data.polygons])
 tree=BVHTree.FromPolygons(verts,faces);gap=min(tree.find_nearest(v.co)[3] for v in proto.data.vertices if v.co.z>-.2);assert gap<.009,('no hanger contact',i,gap);proof.append({'pattern':i,'hanger_contact_gap_m':gap,'supported_contact_pin_count':proto.get('supported_contact_pin_count',0),'hanger_relative_bounds':[lo,hi]})
# Prototype-only experiment; no scene integration or acceptance.
for o in list(bpy.data.objects):
 if o not in prototypes+colliders:bpy.data.objects.remove(o,do_unlink=True)
scene.frame_set(frame0);bpy.context.view_layer.update()
bpy.ops.wm.save_as_mainfile(filepath=str(out))
state.write_text(json.dumps({'pid':os.getpid(),'phase':'prototype_baked_review_pending','candidate':str(out),'total_cloth_mass_kg':.18,'prototype_contacts':proof,'photorealism_accepted':False,'scope':'single fresh native shirt; corrected per-vertex mass; no room integration'},indent=2))
print('SAVED',out,flush=True)
