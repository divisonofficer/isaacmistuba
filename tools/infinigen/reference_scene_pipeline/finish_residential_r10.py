"""Replace box-like top bedding with supported draped textile geometry."""
import bpy,bmesh,math,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];base=ROOT/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full';ref=ROOT/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03'
bpy.ops.wm.open_mainfile(filepath=str(base/'scene_candidate_r9.blend'))
changed=[]
for bed in list(bpy.data.objects):
 key=bed.get('program_key','')
 if not key.endswith(('_master_bed','_bedroom2_bed','_bedroom3_bed')):continue
 white=next(m for m in bed.data.materials if m.name.startswith('ir_sfb_white'))
 throw=next(m for m in bed.data.materials if m.name.startswith('ir_sfb_throw'))
 bm=bmesh.new();bm.from_mesh(bed.data);delete=[]
 for face in bm.faces:
  name=bed.data.materials[face.material_index].name;c=face.calc_center_median()
  if (name.startswith(('ir_sfb_oat','ir_sfb_throw')) or (name.startswith('ir_sfb_white') and c.x>.65 and c.z>.5)):delete.append(face)
 bmesh.ops.delete(bm,geom=delete,context='FACES');bm.to_mesh(bed.data);bm.free()
 w=1.4 if 'bedroom2' in key else 1.6;nx,ny=64,64;verts=[];faces=[];mi=[]
 for i in range(nx+1):
  x=.64+(2.30-.64)*i/nx
  for j in range(ny+1):
   y=-(w/2+.15)+(w+.30)*j/ny
   ex=max(0,x-2.12);ey=max(0,abs(y)-(w/2-.03))
   z=.665-1.5*max(ex,ey)+.012*math.sin(x*15+y*5)*math.sin(y*19+x*3)+.004*math.sin(y*61+x*14)
   verts.append((x,y,z))
 for i in range(nx):
  x=.64+(2.30-.64)*(i+.5)/nx
  for j in range(ny):
   a=i*(ny+1)+j;faces.append((a,a+ny+1,a+ny+2,a+1));mi.append(int(1.35<x<1.84))
 mesh=bpy.data.meshes.new(key+'_draped_textile');mesh.from_pydata(verts,[],faces);mesh.materials.append(white);mesh.materials.append(throw)
 for p,index in zip(mesh.polygons,mi):p.material_index=index;p.use_smooth=True
 cloth=bpy.data.objects.new('Residential03_r10_'+key+'_duvet',mesh);bpy.context.scene.collection.objects.link(cloth);cloth.matrix_world=bed.matrix_world.copy()
 cloth['reference_scene_owner']='dual_unit_residential_floor_03';cloth['program_key']=key+'_draped_duvet';cloth['audit_kind']='fixture'
 solid=cloth.modifiers.new('duvet_textile_thickness','SOLIDIFY');solid.thickness=.008
 changed.append(key)
out=base/'scene_candidate_r10.blend';assert not out.exists();bpy.ops.wm.save_as_mainfile(filepath=str(out))
(ref/'finishing_r10.json').write_text(json.dumps({'source':'scene_candidate_r9.blend','beds_with_actual_draped_mesh':changed,'limitations':'Analytic wrinkles and edge drape; not cloth simulation. Needs direct visual and geometry regression checks.','visual_acceptance':False},indent=2))
