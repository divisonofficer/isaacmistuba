"""Controlled manufactured-profile trial; preserves assembly envelope and shaders."""
import bpy,math,json,hashlib
from pathlib import Path
from mathutils import Vector
ROOT=Path(__file__).resolve().parents[3];base=ROOT/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full';ref=ROOT/'data/venue_refs/floor_plans_v3/commercial_office_floor_02'
src=base/'scene_candidate_r79.blend';out=base/'scene_candidate_r80.blend';assert not out.exists();sha=hashlib.sha256(src.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(src));rows=[]
def profile_mesh(key,profile):
 o=next(o for o in bpy.data.objects if o.get('program_key')==key);assert o.type=='MESH' and not o.parent
 vs=[o.matrix_world@v.co for v in o.data.vertices];lo=[min(p[i] for p in vs) for i in range(3)];hi=[max(p[i] for p in vs) for i in range(3)];cx=(lo[0]+hi[0])/2;cy=(lo[1]+hi[1])/2;rad=(hi[0]-lo[0])/2;h=hi[2]-lo[2];N=96
 verts=[(cx+rad*r*math.cos(math.tau*k/N),cy+rad*r*math.sin(math.tau*k/N),lo[2]+h*z) for z,r in profile for k in range(N)]
 faces=[]
 for j in range(len(profile)-1):
  for k in range(N):faces.append((j*N+k,j*N+(k+1)%N,(j+1)*N+(k+1)%N,(j+1)*N+k))
 faces.extend([tuple(reversed(range(N))),tuple((len(profile)-1)*N+k for k in range(N))]);m=bpy.data.meshes.new(key+'_stepped_profile80');m.from_pydata(verts,[],faces);m.materials.clear()
 for mat in o.data.materials:m.materials.append(mat)
 for f in m.polygons:
  # Only curved axial sidewalls interpolate; annular shelves and end caps stay planar.
  if f.index<(len(profile)-1)*N:
   j=f.index//N;f.use_smooth=abs(profile[j+1][0]-profile[j][0])>1e-8
 o.data=m;o.matrix_world.identity();be=o.modifiers.new('Small_machined_edge_radius','BEVEL');be.width=.00035;be.segments=3;be.limit_method='ANGLE';be.angle_limit=.5;o.modifiers.new('Planar_ledge_normals','WEIGHTED_NORMAL')
 assert len(m.vertices)==len(profile)*N
 rows.append(dict(key=key,profile_normalized=profile,before_bounds_m=[lo,hi],raw_vertices=len(m.vertices),material_names=[m.name for m in m.materials],nominal_edge_radius_m=.00035))
profile_mesh('machine_brew_group',[(0,.91),(.08,.91),(.08,1),(.20,1),(.20,.90),(.71,.90),(.71,.95),(.87,.95),(.87,.89),(1,.89)])
profile_mesh('machine_filter_basket',[(0,.86),(.12,.91),(.72,.94),(.72,1),(.90,1),(.90,.96),(1,.96)])
bpy.context.view_layer.update();bpy.ops.wm.save_as_mainfile(filepath=str(out));assert hashlib.sha256(src.read_bytes()).hexdigest()==sha
(ref/'realism_refinement_r80.json').write_text(json.dumps({'source':str(src),'source_sha256':sha,'candidate':str(out),'trigger':'Full79 independent high: simple cylinder brew head and model-like manufacture','changes':rows,'scope':'Only group/filter axial profiles within original bounds. Existing material slots, lights, cameras, other meshes unchanged. No functional espresso or product-photography certification.','photorealism_accepted':False,'requires':'Same camera/render closeup and surrounding-view comparison; visual acceptance pending.'},indent=2)+'\n');print('SAVED',out,flush=True)
