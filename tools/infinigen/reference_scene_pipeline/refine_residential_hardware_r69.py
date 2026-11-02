"""Restore only19 verified native handle masks;preserve geometry andnonhandle material/shading."""
import bpy,json,hashlib
from pathlib import Path
r=Path('/jarvis/project/robomituba');base=r/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full';ref=r/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';src=base/'scene_candidate_r68.blend';out=base/'scene_candidate_r69.blend';assert not out.exists();sha=hashlib.sha256(src.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(src));metal_source=r/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full/scene_candidate_r78.blend'
with bpy.data.libraries.load(str(metal_source),link=False) as (a,b):b.materials=['DoorR74_satin_stainless']
metal=b.materials[0];assert metal;metal.name='Res69_satin_stainless_hardware';rows=[];skipped=[]
for o in [o for o in bpy.data.objects if o.type=='MESH' and 'DoorFactory' in o.name]:
 me=o.data;a=me.attributes.get('handle')
 if not a:skipped.append({'door':o.name,'reason':'native handle mask missing;no inferred edits'});continue
 assert a.domain=='POINT';values=[x.value for x in a.data];ids={i for i,x in enumerate(values) if x>.5};faces=[f for f in me.polygons if all(i in ids for i in f.vertices)];assert faces and not any(any(i in ids for i in f.vertices) and not all(i in ids for i in f.vertices) for f in me.polygons)
 selected={f.index for f in faces};before=[(f.material_index,f.use_smooth) for f in me.polygons];edges=[e.use_edge_sharp for e in me.edges];verts=hashlib.sha256(repr([tuple(v.co) for v in me.vertices]).encode()).hexdigest();original={me.materials[f.material_index].name for f in faces};assert all('res03_oak' in name for name in original)
 me.materials.append(metal);slot=len(me.materials)-1
 for f in faces:f.material_index=slot;f.use_smooth=True
 cleared=0
 for e in me.edges:
  if all(i in ids for i in e.vertices):cleared+=int(e.use_edge_sharp);e.use_edge_sharp=False
  else:assert edges[e.index]==e.use_edge_sharp
 assert all(before[f.index]==(f.material_index,f.use_smooth) for f in me.polygons if f.index not in selected);assert verts==hashlib.sha256(repr([tuple(v.co) for v in me.vertices]).encode()).hexdigest()
 rows.append({'door':o.name,'verified_handle_faces':len(faces),'previous_materials':sorted(original),'new_material':metal.name,'handle_sharp_edges_cleared':cleared,'geometry_sha256_unchanged':verts,'nonhandle_material_and_smoothing_unchanged':True})
assert len(rows)==19 and len(skipped)==4;bpy.context.view_layer.update();bpy.ops.wm.save_as_mainfile(filepath=str(out));assert hashlib.sha256(src.read_bytes()).hexdigest()==sha;(ref/'realism_refinement_r69.json').write_text(json.dumps({'source':str(src),'source_sha256':sha,'candidate':str(out),'material_source':str(metal_source),'changes':rows,'skipped':skipped,'scope':'Only tagged hardware material/normal flags. No panel/glass/layout/light edits. Missing masks remain unverified.','photorealism_accepted':False,'requires':'Five saved-source gates,controlled bathroom/dressing A/B andfresh independent review'},indent=2));print('Saved',out,'verified doors',len(rows),'skipped',len(skipped),flush=True)
