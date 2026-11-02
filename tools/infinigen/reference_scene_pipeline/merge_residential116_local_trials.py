"""Combine independently reviewed local trials; retain whole-scene FAIL and no promotion."""
import bpy,json,hashlib,array
from pathlib import Path
r=Path(__file__).resolve().parents[3];d=r/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';b=r/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full';src=b/'scene_candidate_r115_draft.blend';donor=b/'scene_candidate_r111_draft.blend';dst=b/'scene_candidate_r116_draft.blend';assert not dst.exists();sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();base_sha=sha(src);donor_sha=sha(donor)
for p in ['bedroom111_review/blind_visual_review.json','stair115_review/blind_visual_review.json']:assert len(json.loads((d/p).read_text())['inspected_paths'])==4
build=json.loads((d/'bedroom110_build.json').read_text());fix=json.loads((d/'bedroom111_support_fix.json').read_text());assert donor_sha==fix['candidate_sha256'];assert base_sha==json.loads((d/'stair115_landing_guard.json').read_text())['candidate_sha256'];names=[n for x in build['replacements'] for n in x['new_objects']+x['lamp_objects_moved']];assert len(names)==len(set(names))==6;bpy.ops.wm.open_mainfile(filepath=str(src));remove={n for x in build['replacements'] for n in [x['old_object']]+x['lamp_objects_moved']};assert len(remove)==6

def fingerprint(o):
 h=hashlib.sha256();h.update(repr((o.type,list(map(list,o.matrix_world)),o.hide_render,o.parent.name if o.parent else None)).encode())
 if o.type=='MESH':
  coords=array.array('f',[0])* (len(o.data.vertices)*3);o.data.vertices.foreach_get('co',coords);h.update(coords.tobytes());indices=array.array('i',[0])*len(o.data.loops);o.data.loops.foreach_get('vertex_index',indices);h.update(indices.tobytes());h.update(repr([m.name if m else None for m in o.data.materials]).encode())
 return h.hexdigest()
bpy.context.view_layer.update();before={o.name:fingerprint(o) for o in bpy.context.scene.objects if o.name not in remove}
for name in remove:assert name in bpy.data.objects;bpy.data.objects.remove(bpy.data.objects[name],do_unlink=True)
with bpy.data.libraries.load(str(donor),link=False) as (s,z):z.objects=list(names)
for o in z.objects:assert o and o.parent is None;bpy.context.scene.collection.objects.link(o)
bpy.context.view_layer.update();after={o.name:fingerprint(o) for o in bpy.context.scene.objects if o.name not in names};differences={'missing':sorted(set(before)-set(after)),'added':sorted(set(after)-set(before)),'changed':[k for k in before.keys()&after.keys() if before[k]!=after[k]],'actual_imported_names':[o.name for o in z.objects]};(d/'combined116_preservation_probe.json').write_text(json.dumps(differences,indent=2));assert before==after,differences
assert len([o for o in bpy.context.scene.objects if o.get('program_key')=='102_master_nightstand'])==0
assert len([o for o in bpy.context.scene.objects if o.get('audit_kind')=='stair_guard' and 'post' in o.name.lower()])==55
bpy.ops.wm.save_as_mainfile(filepath=str(dst));assert sha(src)==base_sha and sha(donor)==donor_sha;(d/'combined116_build.json').write_text(json.dumps({'source':str(src),'source_sha256':base_sha,'donor':str(donor),'donor_sha256':donor_sha,'candidate':str(dst),'candidate_sha256':sha(dst),'imported_objects':names,'removed_objects':sorted(remove),'unrelated_object_geometry_pose_binding_fingerprints_unchanged':len(before),'aggregate_fingerprint_sha256':hashlib.sha256(json.dumps(before,sort_keys=True).encode()).hexdigest(),'guard_post_count':55,'accepted':False,'scope':'Combine local111 nightstands and115 stair. Geometry/world poses/material-slot bindings/hide flags of all unrelated objects unchanged; no whole-shader equivalence or full navigation/visual acceptance. Whole scene still requires full-suite review.'},indent=2));print('RESIDENTIAL116_COMBINED_LOCAL_TRIALS_SAVED')
