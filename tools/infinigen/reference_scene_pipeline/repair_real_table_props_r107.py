"""Repair actual plate/apple supports after native table replacement; preserve106 andnative meshes."""
import bpy,json,hashlib,sys
from pathlib import Path
from mathutils import Vector
from mathutils.bvhtree import BVHTree
R=Path(__file__).resolve().parents[3];sys.path.insert(0,str(Path(__file__).parent));from wc_layout_checks import evaluated_geometry
D=R/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';B=R/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full';S=B/'scene_candidate_r106.blend';O=B/'scene_candidate_r107.blend';assert not O.exists();sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest();hs=sha(S);bpy.ops.wm.open_mainfile(filepath=str(S));parts=[o for o in bpy.context.scene.objects if o.get('program_key')=='breakout_table'];assert len(parts)==1;table=parts[0];plate=next(o for o in bpy.context.scene.objects if o.get('program_key')=='breakout_fruit_plate');fruits=sorted([o for o in bpy.context.scene.objects if str(o.get('program_key','')).startswith('breakout_fruit_') and o!=plate],key=lambda o:o.name);assert len(fruits)==3;rows=[]
def geometry(o):
 ev,me,pts=evaluated_geometry(o);faces=[tuple(f.vertices) for f in me.polygons];ev.to_mesh_clear();return pts,faces
def tree(o):
 p,f=geometry(o);return BVHTree.FromPolygons(p,f)
def settle(o,support,margin):
 before=[list(v) for v in o.matrix_world];pts,faces=geometry(o);samples=list(pts)
 for f in faces:
  samples.append(sum((pts[i] for i in f),Vector())/len(f))
  samples.extend((pts[i]+pts[j])*.5 for i,j in zip(f,f[1:]+f[:1]))
 st=tree(support);deltas=[]
 for p in samples:
  hit=st.ray_cast(Vector((p.x,p.y,2)),Vector((0,0,-1)),3)[0]
  if hit is not None:deltas.append(hit.z-p.z)
 assert deltas;o.location.z+=max(deltas)+margin;bpy.context.view_layer.update();center=o.matrix_world.translation;hit=st.ray_cast(Vector((center.x,center.y,2)),Vector((0,0,-1)),3)[0];o['support_object']=support.name;o['support_z']=hit.z if hit is not None else max(p.z for p in geometry(support)[0]);o['audit_kind']='tabletop_prop';overlap=len(tree(o).overlap(st));assert overlap==0,(o.name,overlap);rows.append({'object':o.name,'support':support.name,'old_matrix':before,'delta_z_m':o.matrix_world.translation.z-before[2][3],'requested_sample_gap_m':margin,'sample_count':len(samples),'surface_triangle_overlaps':overlap})
settle(plate,table,.0003)
for fruit in fruits:settle(fruit,plate,.0005)
bpy.ops.wm.save_as_mainfile(filepath=str(O));assert sha(S)==hs;m=json.load(open(D/'realism_refinement_r106.json'));m.update(source=str(S),source_sha256=hs,candidate=str(O),candidate_sha256=sha(O),change='Repair107:actual plate support string redirected fromdeleted conference primitive to native table;plate and3apples settled byactual evaluated support rays includingface/edge samples,0surface intersections. Oldtablemax included cablebox,not tabletop; no phone waspresent. Native table/chairs/cabinet/light/cameras remain106.',table_prop_support107=rows,photorealism_accepted=False);(D/'realism_refinement_r107.json').write_text(json.dumps(m,indent=2));print('SAVED107',sha(O),flush=True)
