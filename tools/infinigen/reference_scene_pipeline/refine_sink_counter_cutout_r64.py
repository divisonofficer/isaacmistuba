"""Cut finite counter/bowl interference with a shaped solid cutter; add actual drain fitting. Audited before save."""
import bpy,bmesh,json,hashlib,math
from pathlib import Path
from mathutils import Matrix
from mathutils.bvhtree import BVHTree
r=Path('/jarvis/project/robomituba');base=r/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full';ref=r/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';src=base/'scene_candidate_r63.blend';out=base/'scene_candidate_r64.blend';assert not out.exists();sha=hashlib.sha256(src.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(src));records=[];prior=json.loads((ref/'realism_refinement_r62.json').read_text())['changes']
def obj(name,vs,fs,mat,parent=None):
 me=bpy.data.meshes.new(name);me.from_pydata(vs,[],fs);me.update()
 if mat:me.materials.append(mat)
 bm=bmesh.new();bm.from_mesh(me);bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces));bm.to_mesh(me);bm.free();o=bpy.data.objects.new(name,me);bpy.context.collection.objects.link(o)
 if parent:o.parent=parent;o.matrix_parent_inverse=Matrix.Identity(4);o.matrix_basis=Matrix.Identity(4);o['audit_kind']='detail';o['program_key']=parent['program_key']+'__detail__'+name
 return o
for c in prior:
 parent=bpy.data.objects[c['kitchen']];sy=c['sink_center_y_local'];bowl=next(x for x in bpy.data.objects if x.parent==parent and x.name.startswith('FormedSink_'));mi=next(i for i,m in enumerate(parent.data.materials) if m and m.name=='ir_kit_top');faces=[p for p in parent.data.polygons if p.material_index==mi];ids=sorted(set(i for f in faces for i in f.vertices));assert len(ids)==32;lookup={i:j for j,i in enumerate(ids)};counter=obj('CutCounter_'+parent['program_key'],[list(parent.data.vertices[i].co) for i in ids],[tuple(lookup[i] for i in f.vertices) for f in faces],parent.data.materials[mi],parent)
 bm=bmesh.new();bm.from_mesh(parent.data);bm.verts.ensure_lookup_table();bmesh.ops.delete(bm,geom=[bm.verts[i] for i in ids],context='VERTS');bm.to_mesh(parent.data);bm.free();parent.data.update()
 # Envelope encloses measured evaluated bowl at slab heights,with clearance and8mm+rim cover.
 rings=[(.192,.283,.85),(.205,.295,.889),(.225,.308,.8975),(.225,.308,.94)];N=128;vs=[]
 for rx,ry,z in rings:
  for k in range(N):
   a=k*math.tau/N;co=math.cos(a);si=math.sin(a);vs.append((.32+rx*math.copysign(abs(co)**.25,co),sy+ry*math.copysign(abs(si)**.25,si),z))
 fs=[tuple(reversed(range(N))),tuple((len(rings)-1)*N+k for k in range(N))]+[(j*N+k,j*N+(k+1)%N,(j+1)*N+(k+1)%N,(j+1)*N+k) for j in range(len(rings)-1) for k in range(N)];cut=obj('SinkCutTool',vs,fs,None,parent);cut.matrix_world=parent.matrix_world.copy();bpy.context.view_layer.update();bpy.context.view_layer.objects.active=counter;counter.select_set(True);mod=counter.modifiers.new('Measured bowl clearance','BOOLEAN');mod.operation='DIFFERENCE';mod.solver='EXACT';mod.object=cut;bpy.ops.object.modifier_apply(modifier=mod.name);bpy.data.objects.remove(cut,do_unlink=True)
 bpy.context.view_layer.update();deps=bpy.context.evaluated_depsgraph_get();trees=[]
 for o in [bowl,counter]:
  ev=o.evaluated_get(deps);me=ev.to_mesh();trees.append(BVHTree.FromPolygons([v.co.copy() for v in me.vertices],[tuple(p.vertices) for p in me.polygons]));ev.to_mesh_clear()
 overlap=len(trees[0].overlap(trees[1]));assert overlap==0,('bowl-counter triangle overlaps',parent.name,overlap)
 # Drain neck/strainer flange replaces bare opening; no brand or plumbing simulation claim.
 metal=bowl.data.materials[0];profile=[(.031,.7305),(.031,.732),(.021,.732),(.019,.727),(.017,.711),(.017,.708),(.019,.708),(.021,.727)];vs=[];N=64
 for rad,z in profile:
  for k in range(N):a=k*math.tau/N;vs.append((.32+rad*math.cos(a),sy+rad*math.sin(a),z))
 fs=[(j*N+k,j*N+(k+1)%N,((j+1)%len(profile))*N+(k+1)%N,((j+1)%len(profile))*N+k) for j in range(len(profile)) for k in range(N)];drain=obj('DrainFitting_'+parent['program_key'],vs,fs,metal,parent)
 for p in drain.data.polygons:p.use_smooth=True
 records.append({'kitchen':parent.name,'previous_finite_overlap_evidence':'formed_sink_fit_audit_r63.json','new_evaluated_bowl_counter_triangle_overlaps':overlap,'counter_cutter_top_half_extents_m':[.225,.308],'drain_fitting_outer_diameter_m':.062,'drain_neck_inner_diameter_m':.034,'unchanged':'Bowl geometry/shader,counter shader,layout,lights/cameras. Counter onlycut locally tofit actual bowl.'})
assert len(records)==2;bpy.context.view_layer.update();bpy.ops.wm.save_as_mainfile(filepath=str(out));assert hashlib.sha256(src.read_bytes()).hexdigest()==sha;(ref/'realism_refinement_r64.json').write_text(json.dumps({'source':str(src),'source_sha256':sha,'candidate':str(out),'changes':records,'photorealism_accepted':False,'scope':'Actual evaluated bowl/countertriangle overlap gate before save. Not fullscene collision/navigation orcompleteplumbing.','requires':'Saved-source audits andwide+manufacture closeup direct/blind comparison'},indent=2));print('Saved',out,flush=True)
