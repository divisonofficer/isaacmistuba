"""Restore material separation on actual native POINT-domain handle masks; no door motion or geometry edits."""
import bpy, json, hashlib, struct
from pathlib import Path
from material_detail import material
from surface_realism import enrich
r=Path('/jarvis/project/robomituba');base=r/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full';ref=r/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';src=base/'scene_candidate_r73.blend';out=base/'scene_candidate_r74.blend';assert not out.exists();sha=hashlib.sha256(src.read_bytes()).hexdigest();bpy.ops.wm.open_mainfile(filepath=str(src))
metal,*_=material('DoorR74_satin_stainless',(.55,.565,.58),.25,1);detail=enrich(metal,'bare_metal');rows=[]
for o in bpy.data.objects:
 if o.type!='MESH' or 'DoorFactory' not in o.name:continue
 attr=o.data.attributes.get('handle');assert attr and attr.domain=='POINT',(o.name,'Missing native POINT handle mask')
 values=[float(x.value) for x in attr.data];selected=[p.index for p in o.data.polygons if all(values[i]>.5 for i in p.vertices)];partial=[p.index for p in o.data.polygons if any(values[i]>.5 for i in p.vertices) and not all(values[i]>.5 for i in p.vertices)];assert selected and not partial,(o.name,len(selected),len(partial))
 vertices=hashlib.sha256(b''.join(struct.pack('3f',*v.co) for v in o.data.vertices)).hexdigest();before=[p.material_index for p in o.data.polygons];nonhandles={p.index:p.material_index for p in o.data.polygons if p.index not in set(selected)};original={o.data.materials[before[i]].name for i in selected};slot=len(o.data.materials);o.data.materials.append(metal)
 for i in selected:o.data.polygons[i].material_index=slot
 assert all(o.data.polygons[i].material_index==idx for i,idx in nonhandles.items());assert hashlib.sha256(b''.join(struct.pack('3f',*v.co) for v in o.data.vertices)).hexdigest()==vertices
 rows.append({'door':o.name,'native_mask_domain':'POINT','native_mask_values':sorted(set(values)),'handle_faces':len(selected),'mixed_tag_faces':0,'before_handle_materials':sorted(original),'after_handle_material':metal.name,'geometry_sha256_unchanged':vertices,'nonhandle_face_material_indices_unchanged':True})
assert len(rows)==12;bpy.context.view_layer.update();bpy.ops.wm.save_as_mainfile(filepath=str(out));assert hashlib.sha256(src.read_bytes()).hexdigest()==sha;(ref/'realism_refinement_r74.json').write_text(json.dumps({'source':str(src),'source_sha256':sha,'candidate':str(out),'trigger':'Full71 fresh review: native lever/rosette read as carved timber. Actual probe confirms all12native door handle masks assigned office02_door_oak.','changes':rows,'material_detail':detail,'unchanged':'Door mesh/pose/clearance,nonhandle timber/materialindices,lighting/camera','photorealism_accepted':False,'requires':'Saved-source four audits andsamecamera foreground/background handle direct+blind review'},indent=2));print('Saved',out,flush=True)
