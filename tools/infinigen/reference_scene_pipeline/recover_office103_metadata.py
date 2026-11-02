"""Recover metadata after Blender mutated the original object-name list during append.
Never overwrites/resaves source or candidate. Revalidates all baseline object bindings.
"""
import bpy,json,hashlib
from pathlib import Path
from mathutils import Vector
R=Path(__file__).resolve().parents[3];D=R/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';B=R/'out/infinigen_v2/kr_commercial_office_floor_02_48712502/full';out=D/'realism_refinement_r103.json';assert not out.exists();S=B/'scene_candidate_r102.blend';C=B/'scene_candidate_r103.blend';sha=lambda p:hashlib.sha256(Path(p).read_bytes()).hexdigest();hs,hc=sha(S),sha(C)
def signatures():return {o.name:([list(x) for x in o.matrix_world],o.data.name if o.data else None,[m.name if m else None for m in o.data.materials] if o.type=='MESH' else []) for o in bpy.context.scene.objects}
bpy.ops.wm.open_mainfile(filepath=str(S));baseline=signatures();bpy.ops.wm.open_mainfile(filepath=str(C));candidate=signatures()
for name,value in baseline.items():assert candidate[name]==value,name
info=json.loads((D/'outdoor_tree_candidates/scope.json').read_text());entry=next(x for x in info['assets'] if x['id']=='PH_tree_small_02');records=[]
for o in bpy.context.scene.objects:
 if not o.name.startswith('Office02_r103_real_tree_'):continue
 pts=[o.matrix_world@Vector(v) for v in o.bound_box];records.append({'object':o.name,'matrix':[list(v) for v in o.matrix_world],'bounds_lo':[min(p[k] for p in pts) for k in range(3)],'bounds_hi':[max(p[k] for p in pts) for k in range(3)],'native_faces':len(o.data.polygons),'shared_mesh':o.data.name})
assert len(records)==12
meta=json.loads((D/'realism_refinement_r102.json').read_text());meta.update(source=str(S),source_sha256=hs,candidate=str(C),candidate_sha256=hc,change='Only12native-scale real tree instances and exterior grade ring. Original interior transforms/data/material bindings preserved; no heldHDR99 or facade module.',exterior_trees={'asset':entry,'prototype_blend':str(D/'outdoor_tree_candidates/review_studio.blend'),'prototype_sha256':info['source_sha256'],'records':records,'existing_object_count_preserved':len(baseline),'grade_object':'Office02_r103_exterior_grade','grade_z_m':-.02,'limitations':'Repeated single species; foreground trees only. Simple authored diffuse planar grade, no city/buildings or reference-complete landscape. Physical/visual gates pending.'},metadata_recovery={'reason':'Blender append mutated supplied object-name list intoObject references, JSON write failed after save. Copy list now used in producer.','initial_log':'exterior_r103_metadata_initial_failure.log','baseline_bindings_rechecked':len(baseline),'candidate_not_resaved':True},photorealism_accepted=False)
assert sha(S)==hs and sha(C)==hc;out.write_text(json.dumps(meta,indent=2))
