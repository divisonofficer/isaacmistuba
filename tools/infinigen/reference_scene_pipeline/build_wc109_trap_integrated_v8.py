"""Boolean integrate trap wall and carve open continuous flow void. Diagnostic only."""
import bpy,json,hashlib,math,bmesh
from pathlib import Path
r=Path(__file__).resolve().parents[3];d=r/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';p=d/'wc109_trap_pilot_v8';assert not p.exists();p.mkdir();source=d/'wc109_trap_pilot_v3/candidate.blend';before=hashlib.sha256(source.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(source));body=bpy.data.objects['NativeFullTankWC100'];trap=bpy.data.objects['WC109_continuous_hollow_S_trap'];meta=json.loads((d/'wc109_trap_pilot_v3/build.json').read_text());N=meta['circumference_samples'];count=meta['ring_count'];assert len(trap.data.vertices)==count*2*N
original_bounds=([min(v.co[k] for v in body.data.vertices) for k in range(3)],[max(v.co[k] for v in body.data.vertices) for k in range(3)])
def volume(wall,extend=False):
 rings=[[tuple(trap.data.vertices[j*2*N+wall*N+i].co) for i in range(N)] for j in range(count)]
 if extend:rings=[[(*v[:2],v[2]+.10) for v in rings[0]]]+rings+[[(*v[:2],-.04) for v in rings[-1]]]
 verts=[v for ring in rings for v in ring];faces=[]
 for j in range(len(rings)-1):
  for i in range(N):faces.append((j*N+i,j*N+(i+1)%N,(j+1)*N+(i+1)%N,(j+1)*N+i))
 faces +=[tuple(reversed(range(N))),tuple((len(rings)-1)*N+i for i in range(N))]
 me=bpy.data.meshes.new('WC109_construction_volume');me.from_pydata(verts,[],faces)
 import bmesh
 bm=bmesh.new();bm.from_mesh(me);bmesh.ops.recalc_face_normals(bm,faces=bm.faces);assert all(e.is_manifold for e in bm.edges);bm.to_mesh(me);bm.free();me.materials.append(body.data.materials[0]);o=bpy.data.objects.new(me.name,me);bpy.context.scene.collection.objects.link(o);return o
# Isolate the closed bowl component (native indices 0..30791); retain other components untouched.
original=body.data;rest=body.copy();rest.data=original.copy();rest.name='WC109_preserved_native_aux';bpy.context.scene.collection.objects.link(rest)
bm=bmesh.new();bm.from_mesh(rest.data);bm.verts.ensure_lookup_table();bmesh.ops.delete(bm,geom=[v for v in bm.verts if not 35228<=v.index<49548],context='VERTS');bm.to_mesh(rest.data);bm.free()
preserved=body.copy();preserved.data=original.copy();preserved.name='WC109_unmodified_seat_tank_hardware';bpy.context.scene.collection.objects.link(preserved);bm=bmesh.new();bm.from_mesh(preserved.data);bm.verts.ensure_lookup_table();bmesh.ops.delete(bm,geom=[v for v in bm.verts if v.index<30792 or 35228<=v.index<49548],context='VERTS');bm.to_mesh(preserved.data);bm.free()
body.data=original.copy();bm=bmesh.new();bm.from_mesh(body.data);bm.verts.ensure_lookup_table();bmesh.ops.delete(bm,geom=[v for v in bm.verts if v.index>=30792],context='VERTS');bmesh.ops.recalc_face_normals(bm,faces=bm.faces);assert all(e.is_manifold for e in bm.edges);bm.to_mesh(body.data);bm.free()
outer=volume(1);inner=volume(0,True);body.data=body.data.copy();bpy.context.view_layer.objects.active=body;body.select_set(True)
counts=[]
for op,tool in [('UNION',outer),('DIFFERENCE',inner)]:
 m=body.modifiers.new('WC109_integrate_'+op,'BOOLEAN');m.operation=op;m.solver='EXACT';m.object=tool;m.use_hole_tolerant=True;bpy.ops.object.modifier_apply(modifier=m.name);counts.append({'operation':op,'vertices':len(body.data.vertices),'faces':len(body.data.polygons)});assert len(body.data.polygons)>25000
# Close native auxiliary boundary loops, then carve the same physical bore.
bm=bmesh.new();bm.from_mesh(rest.data);boundary=[e for e in bm.edges if e.is_boundary];filled=bmesh.ops.holes_fill(bm,edges=boundary,sides=0);bmesh.ops.recalc_face_normals(bm,faces=bm.faces);aux_closed=all(e.is_manifold for e in bm.edges);assert aux_closed;bm.to_mesh(rest.data);bm.free()
bpy.context.view_layer.objects.active=rest;m=rest.modifiers.new('WC109_native_aux_routed_void','BOOLEAN');m.operation='DIFFERENCE';m.solver='EXACT';m.object=inner;bpy.ops.object.modifier_apply(modifier=m.name)
bm=bmesh.new();bm.from_mesh(rest.data);aux_after={'boundary_edges':sum(e.is_boundary for e in bm.edges),'nonmanifold_edges':sum(not e.is_manifold for e in bm.edges)};bm.free()
for o in [outer,inner,trap]:bpy.data.objects.remove(o,do_unlink=True)
bm=bmesh.new();bm.from_mesh(body.data);bowl_topology={'vertices':len(bm.verts),'faces':len(bm.faces),'boundary_edges':sum(e.is_boundary for e in bm.edges),'nonmanifold_edges':sum(not e.is_manifold for e in bm.edges)};bm.free()
# Rejoin unchanged auxiliary native components only after isolated bowl Boolean.
bpy.ops.object.select_all(action='DESELECT');body.select_set(True);rest.select_set(True);preserved.select_set(True);bpy.context.view_layer.objects.active=body;bpy.ops.object.join()
new_bounds=([min(v.co[k] for v in body.data.vertices) for k in range(3)],[max(v.co[k] for v in body.data.vertices) for k in range(3)])
body['wc109_interior_extension']='Boolean union swept outer porcelain, then difference open bore, native body not scaled';bpy.ops.wm.save_as_mainfile(filepath=str(p/'candidate.blend'));assert hashlib.sha256(source.read_bytes()).hexdigest()==before;(p/'views.json').write_text((d/'wc109_trap_pilot_v3/views.json').read_text());(p/'build.json').write_text(json.dumps({'source':str(source),'source_sha256':before,'candidate':str(p/'candidate.blend'),'candidate_sha256':hashlib.sha256((p/'candidate.blend').read_bytes()).hexdigest(),'operations':counts,'isolated_bowl_topology':bowl_topology,'auxiliary_after_routed_void':aux_after,'filled_boundary_faces':len(filled['faces']),'body_bounds_before':original_bounds,'body_bounds_after':new_bounds,'scale_unchanged':True,'construction_cutters_saved':False,'scope':'Diagnostic integrated native factory body with real swept outlet void. Auxiliary body interference unresolved. No water seal/plumbing acceptance, full self-intersection or room clearance claim. RGB and cavity audit required.','accepted':False},indent=2));print('WC109_COMPONENT_SOLIDS_V8_SAVED')
