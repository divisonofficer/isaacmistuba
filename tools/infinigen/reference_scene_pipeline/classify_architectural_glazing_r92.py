"""Correct new external window semantics; geometry/world/materials unchanged from91."""
import bpy,json,hashlib
from pathlib import Path
R=Path(__file__).resolve().parents[3];D=R/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';B=R/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full';S=B/'scene_candidate_r91.blend';O=B/'scene_candidate_r92.blend';assert not O.exists();meta=json.loads((D/'realism_refinement_r91.json').read_text());audit=json.loads((D/'east_glazing_saved_audit_r91.json').read_text());assert audit['pass'];bpy.ops.wm.open_mainfile(filepath=str(S))
def geom(o):
 return {'vertices':[list(v.co) for v in o.data.vertices],'faces':[list(f.vertices) for f in o.data.polygons],'matrix':[list(v) for v in o.matrix_world],'materials':[m.name if m else None for m in o.data.materials]}
rows=[]
for row in meta['records']:
 o=bpy.data.objects[row['object']];before=geom(o);old=o.get('audit_kind','furniture');o['audit_kind']='architectural_glazing';o['saved_installation_audit']='east_glazing_saved_audit_r92.json';assert geom(o)==before;rows.append({'object':o.name,'old_default_kind':old,'new_kind':o['audit_kind'],'mesh_material_transform_unchanged':True})
bpy.ops.wm.save_as_mainfile(filepath=str(O));meta.update(source=str(S),source_sha256=hashlib.sha256(S.read_bytes()).hexdigest(),candidate=str(O),candidate_sha256=hashlib.sha256(O.read_bytes()).hexdigest(),geometry_parent_revision=91,retained_revision=88,classification_correction=rows,change='Source91 geometry/world unchanged; classify two facade windows as architectural_glazing rather than default ground furniture. Physical saved opening gate mandatory before RGB.');(D/'realism_refinement_r92.json').write_text(json.dumps(meta,indent=2)+'\n');print('ARCHITECTURAL_TAG_R92_SAVED',flush=True)
