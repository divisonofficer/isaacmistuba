"""Actual initial native doors test body tint preservation inRAM;never rerun historical fitout."""
import bpy,pathlib,json,hashlib
from native_component_materials import assign_door_body_preserving_hardware
root=pathlib.Path('/jarvis/project/robomituba');src=root/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full/scene_mat2.blend'
with bpy.data.libraries.load(str(src),link=False) as (a,b):b.objects=[n for n in a.objects if 'DoorFactory' in n]
body=bpy.data.materials.new('validation_only_residential_body');rows=[]
for o in b.objects:
 if not o or o.type!='MESH':continue
 me=o.data;before=[f.material_index for f in me.polygons];slots=len(me.materials);coords=[tuple(v.co) for v in me.vertices];a=me.attributes.get('handle')
 try:result=assign_door_body_preserving_hardware(o,body)
 except ValueError as error:
  assert slots==len(me.materials) and before==[f.material_index for f in me.polygons];rows.append({'door':o.name,'status':'refused_without_mutation','reason':str(error)});continue
 if a.domain=='POINT':values=[v.value for v in a.data];handles={f.index for f in me.polygons if all(values[i]>.5 for i in f.vertices)}
 else:handles={f.index for f in me.polygons if a.data[f.index].value>.5}
 protected=handles|{i for i,mi in enumerate(before) if me.materials[mi] and 'glass' in me.materials[mi].name.lower()};assert all(me.polygons[i].material_index==before[i] for i in protected);assert all(f.material_index==slots for f in me.polygons if f.index not in protected);assert coords==[tuple(v.co) for v in me.vertices];rows.append({'door':o.name,'status':'preserved_native_hardware_glass','handle_faces':len(handles),'protected_faces':len(protected),'native_handle_materials':sorted({me.materials[before[i]].name for i in handles})})
assert any(x['status']=='preserved_native_hardware_glass' for x in rows);p=root/'data/venue_refs/floor_plans_v3/residential_native_door_material_validation.json';p.write_text(json.dumps({'source':str(src),'source_sha256':hashlib.sha256(src.read_bytes()).hexdigest(),'helper_sha256':hashlib.sha256((root/'tools/infinigen/reference_scene_pipeline/native_component_materials.py').read_bytes()).hexdigest(),'caller_sha256':hashlib.sha256((root/'tools/infinigen/reference_scene_pipeline/fit_residential.py').read_bytes()).hexdigest(),'records':rows,'scope':'Actual initial native doors inRAM;exact native hardware/glass face indices andvertex geometry preserved. Unidentifiable masks refuse mutation. Historical fitout/.blend snapshots not regenerated.','photorealism_accepted':False},indent=2));print(json.dumps({'doors':len(rows),'preserved':sum(x['status']=='preserved_native_hardware_glass' for x in rows),'refused_unchanged':sum(x['status']=='refused_without_mutation' for x in rows)}),flush=True)
