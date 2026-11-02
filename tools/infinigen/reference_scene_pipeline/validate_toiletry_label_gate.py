"""Actual failed andcorrected rendered prototypes test triangle gate,not a synthetic mesh fixture."""
import bpy,pathlib,json,hashlib
from audit_native_toiletries import overlap_count
root=pathlib.Path('/jarvis/project/robomituba');ref=root/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';origin=bpy.data.objects.new('AuditIdentity',None);bpy.context.collection.objects.link(origin);rows=[]
for folder,want_fail in [('native_toiletries_studio68_configured',True),('native_toiletries_studio68_configured_fit02',False)]:
 src=ref/folder/'studio.blend';names=tuple(n for seed in [48712600,48712601,48712602] for n in [f'ToiletryNative_body_{seed}',f'ToiletryNative_fitted_label_{seed}'])
 with bpy.data.libraries.load(str(src),link=False) as (a,b):b.objects=list(names)
 loaded=dict(zip(names,b.objects));assert all(loaded.values())
 for o in loaded.values():bpy.context.collection.objects.link(o)
 bpy.context.view_layer.update();deps=bpy.context.evaluated_depsgraph_get();cases=[]
 for seed in [48712600,48712601,48712602]:
  count=overlap_count(loaded[f'ToiletryNative_body_{seed}'],loaded[f'ToiletryNative_fitted_label_{seed}'],origin,deps);assert (count>0)==want_fail,(folder,seed,count);cases.append({'seed':seed,'body_label_overlap_count':count,'expected_gate_reject':want_fail})
 rows.append({'source':str(src),'source_sha256':hashlib.sha256(src.read_bytes()).hexdigest(),'cases':cases})
 for o in loaded.values():bpy.data.objects.remove(o,do_unlink=True)
out=root/'data/venue_refs/floor_plans_v3/toiletry_label_gate_validation.json';out.write_text(json.dumps({'actual_prototype_controls':rows,'auditor_sha256':hashlib.sha256((root/'tools/infinigen/reference_scene_pipeline/audit_native_toiletries.py').read_bytes()).hexdigest(),'success':True,'photorealism_accepted':False,'scope':'Real failed3 prototypes rejected;corrected3 prototypes pass. Doesnot certify all other assembly orappearance conditions.'},indent=2));print('Actual failed3 rejected andcorrected3 passed',flush=True)
