"""Classify the actual floor-contact part as furniture; keep chair geometry/pose."""
import bpy,json,hashlib
from pathlib import Path
R=Path(__file__).resolve().parents[3]
D=R/'data/venue_refs/floor_plans_v3/commercial_office_floor_02'
B=R/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full'
source=B/'scene_candidate_r100.blend';out=B/'scene_candidate_r101.blend';assert not out.exists()
gate=json.loads((D/'breakout_chairs_saved_audit_r100.json').read_text());assert gate['pass']
meta=json.loads((D/'realism_refinement_r100.json').read_text())
sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest()
assert sha(source)==meta['candidate_sha256']==gate['source_sha256']
bpy.ops.wm.open_mainfile(filepath=str(source));bpy.context.view_layer.update()
def geometry(obj):
    return hashlib.sha256(repr(([tuple(v.co) for v in obj.data.vertices],
        [tuple(p.vertices) for p in obj.data.polygons],[[tuple(x.uv) for x in layer.data] for layer in obj.data.uv_layers],
        [list(v) for v in obj.matrix_world],[m.name if m else None for m in obj.data.materials])).encode()).hexdigest()
changes=[]
for row in meta['breakout_chair_records']:
    objects=[bpy.data.objects[name] for name in row['parts']]
    before={o.name:geometry(o) for o in objects}
    contact=min(objects,key=lambda o:min((o.matrix_world@v.co).z for v in o.data.vertices))
    for i,obj in enumerate(objects):
        old_key=obj.get('program_key');old_kind=obj.get('audit_kind')
        obj['program_key']=row['role'] if obj==contact else row['role']+f'_component{i}'
        obj['audit_kind']='furniture' if obj==contact else 'chair_component'
        if old_key!=obj['program_key'] or old_kind!=obj['audit_kind']:
            changes.append({'object':obj.name,'old_key':old_key,'old_kind':old_kind,'new_key':obj['program_key'],'new_kind':obj['audit_kind']})
    assert all(geometry(obj)==before[obj.name] for obj in objects)
    row['furniture_contact_part']=contact.name
assert changes
bpy.ops.wm.save_as_mainfile(filepath=str(out))
assert sha(source)==meta['candidate_sha256']
meta.update(source=str(source),source_sha256=sha(source),candidate=str(out),candidate_sha256=sha(out),
    change='Classification-only repair of source100. Actual floor-contact part becomes the furniture representative; seat/shell remain assembly components. Native vertices/UV,transforms/material assignments unchanged.',
    breakout_chair_classification_correction=changes,
    classification_diagnosis={'failed_generic_gate':'geometry_audit_r100.json','passed_assembly_gate':'breakout_chairs_saved_audit_r100.json',
        'reason':'Generic floor audit tested the elevated seat/shell alone as furniture. All four actual three-part assemblies already supported on floor; no pose/scale correction required.'},
    photorealism_accepted=False)
(D/'realism_refinement_r101.json').write_text(json.dumps(meta,indent=2))
print('BREAKOUT_CHAIR_ROLES101_SAVED',len(changes),flush=True)
