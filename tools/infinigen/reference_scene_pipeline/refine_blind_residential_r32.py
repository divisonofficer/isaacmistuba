"""Blind-review correction: manufactured continuous washbasin surface instead of five boxes."""
import bpy,bmesh,json,hashlib,math
from pathlib import Path
from material_detail import material
ROOT=Path(__file__).resolve().parents[3];base=ROOT/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full';ref=ROOT/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';source=base/'scene_review_r30_packed.blend';out=base/'scene_candidate_r32.blend';assert not out.exists();sha=hashlib.sha256(source.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(source));ceramic=material('BlindR1_vitreous_basin',(.84,.835,.815),.13)[0];records=[]
for o in list(bpy.data.objects):
 if not o.get('program_key','').endswith('_vanity') or 'HomeVanityFactory' not in o.name:continue
 oldmat=next((i for i,m in enumerate(o.data.materials) if m and 'ceramic_white' in m.name),None)
 assert oldmat is not None,o.name
 bm=bmesh.new();bm.from_mesh(o.data);faces=[f for f in bm.faces if f.material_index==oldmat];verts=set(v for f in faces for v in f.verts);assert verts
 # Five boxes lie within this exact native basin envelope.
 low=[min(v.co[i] for v in verts) for i in range(3)];high=[max(v.co[i] for v in verts) for i in range(3)];assert high[0]-low[0]<.41 and high[1]-low[1]<.51
 bmesh.ops.delete(bm,geom=list(verts),context='VERTS');bm.to_mesh(o.data);bm.free()
 # Closed ceramic shell cross-section, with a true open drain aperture.
 profile=[(.022,.022,.715,2),(.14,.19,.715,4),(.185,.235,.724,4),(.199,.249,.775,4),(.200,.250,.790,4),(.198,.248,.795,4),(.190,.240,.795,4),(.187,.237,.790,4),(.178,.228,.770,4),(.142,.188,.744,3),(.075,.100,.733,2),(.022,.022,.731,2)]
 vertices=[];N=96
 for rx,ry,z,power in profile:
  for k in range(N):
   t=k*math.tau/N;c=math.cos(t);s=math.sin(t);vertices.append((.28+rx*math.copysign(abs(c)**(2/power),c),ry*math.copysign(abs(s)**(2/power),s),z))
 faces=[]
 for j in range(len(profile)):
  nextj=(j+1)%len(profile)
  for k in range(N):faces.append((j*N+k,j*N+(k+1)%N,nextj*N+(k+1)%N,nextj*N+k))
 mesh=bpy.data.meshes.new('BlindR1_continuous_ceramic_shell');mesh.from_pydata(vertices,[],faces);mesh.materials.append(ceramic)
 bm=bmesh.new();bm.from_mesh(mesh);bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces));bm.to_mesh(mesh);bm.free()
 for f in mesh.polygons:f.use_smooth=True
 child=bpy.data.objects.new('BlindR1_'+o['program_key']+'_formed_basin',mesh);bpy.context.scene.collection.objects.link(child);child.parent=o;child['reference_scene_owner']='dual_unit_residential_floor_03';child['program_key']=o['program_key']+'_formed_basin';child['audit_kind']='detail'
 sub=child.modifiers.new('Continuous_cast_surface','SUBSURF');sub.levels=1;sub.render_levels=1
 # Remaining cabinet and top acquire realistic small edge radii without moving layout.
 if not any(m.type=='BEVEL' for m in o.modifiers):
  mod=o.modifiers.new('Manufactured_cabinet_edges','BEVEL');mod.width=.0012;mod.segments=3;mod.limit_method='ANGLE';mod.angle_limit=.5
 records.append({'vanity':o['program_key'],'basin_outer_m':[.4,.5],'rim_height_m':.795,'bowl_floor_m':.731,'drain_aperture_diameter_m':.044,'mesh_quads':len(faces),'old_basin_bounds':[low,high]})
bpy.ops.wm.save_as_mainfile(filepath=str(out));assert hashlib.sha256(source.read_bytes()).hexdigest()==sha
(ref/'realism_refinement_r32.json').write_text(json.dumps({'source':str(source),'source_sha256':sha,'candidate':str(out),'blind_review_trigger':'Boxlike washbasin reads as assembly of planes','changes':records,'unchanged':'WC actual bowl already hollow; no speculative carving based on image alone','photorealism_accepted':False},indent=2));print(records,flush=True)
