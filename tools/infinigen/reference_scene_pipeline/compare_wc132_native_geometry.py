"""Read-only actual current/native product comparison, including literal source digest and live loaded coordinates."""
import bpy,json,array,hashlib,sys
from pathlib import Path
R=Path(__file__).resolve().parents[3];sys.path.insert(0,str(Path(__file__).parent));from compact_wc_contract import mesh_geometry_hash
D=R/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';src=R/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full/scene_candidate_r132_draft.blend';before=hashlib.sha256(src.read_bytes()).hexdigest();c=json.loads((D/'native_fullsize_wc100/contract.json').read_text());bpy.ops.wm.open_mainfile(filepath=str(src));o=bpy.data.objects['Residential03_101_bathroom2_wc'];product=Path(c['prototype_source']);product_sha=hashlib.sha256(product.read_bytes()).hexdigest()
with bpy.data.libraries.load(str(product),link=False) as (av,loaded):loaded.objects=[c['object']]
p=loaded.objects[0];bpy.context.scene.collection.objects.link(p);bpy.context.view_layer.update()
def summary(x):return {'name':x.name,'vertices':len(x.data.vertices),'faces':len(x.data.polygons),'loops':len(x.data.loops),'raw_geometry_sha256':mesh_geometry_hash(x.data),'matrix_world':[list(r) for r in x.matrix_world],'bounds_local_m':[[min(v.co[k] for v in x.data.vertices) for k in range(3)],[max(v.co[k] for v in x.data.vertices) for k in range(3)]],'custom_properties':{k:str(v)[:500] for k,v in x.items()},'material_slots':[m.name if m else None for m in x.data.materials]}
a=summary(o);b=summary(p);max_delta=None;loop_equal=False
if len(o.data.vertices)==len(p.data.vertices):max_delta=max((v.co-w.co).length for v,w in zip(o.data.vertices,p.data.vertices))
if len(o.data.loops)==len(p.data.loops):loop_equal=all(v.vertex_index==w.vertex_index for v,w in zip(o.data.loops,p.data.loops))
assert hashlib.sha256(src.read_bytes()).hexdigest()==before
out={'source':str(src),'source_sha256':before,'blender_version':bpy.app.version_string,'current':a,'loaded_native_product':b,'contract_geometry_sha256':c['mesh_geometry_sha256'],'product_file_sha256':product_sha,'product_file_matches_contract':product_sha==c['prototype_source_sha256'],'maximum_corresponding_vertex_displacement_m':max_delta,'corresponding_loop_vertex_indices_identical':loop_equal,'scope':'Raw loaded mesh comparison only. No candidate edits or coordinate assumptions if counts/topology differ.'};(D/'wc132_native_comparison.json').write_text(json.dumps(out,indent=2));print('WC132_NATIVE_COMPARE',out,flush=True)
