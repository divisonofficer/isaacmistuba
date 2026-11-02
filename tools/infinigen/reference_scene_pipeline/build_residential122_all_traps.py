"""Batch remaining eight native WCs with the two-room tested routed interior, still unapproved."""
import bpy,json,hashlib,sys
from pathlib import Path
r=Path(__file__).resolve().parents[3];sys.path.insert(0,str(Path(__file__).parent));from compact_wc_contract import mesh_geometry_hash
from wc_layout_checks import bounds
base=r/'out/infinigen_v2/kr_dual_unit_residential_floor_03_48712503/full';d=r/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';src=base/'scene_candidate_r121_draft.blend';dst=base/'scene_candidate_r122_draft.blend';assert not dst.exists();sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();before=sha(src);bpy.ops.wm.open_mainfile(filepath=str(src));product=d/'wc117_support_clearance_trial/candidate.blend'
with bpy.data.libraries.load(str(product),link=False) as (s,z):z.objects=['NativeFullTankWC100']
proto=z.objects[0];native=proto.data.copy();native.transform(proto.matrix_world);expected=mesh_geometry_hash(native);targets=[o for o in bpy.context.scene.objects if o.type=='MESH' and str(o.get('program_key','')).endswith('_wc')];assert len(targets)==10
extent=lambda m:[[min(v.co[k] for v in m.vertices) for k in range(3)],[max(v.co[k] for v in m.vertices) for k in range(3)]]
upper=lambda m:{tuple(round(v.co[k],6) for k in range(3)) for v in m.vertices if v.co.z>.385}
rows=[];retained=[]
for o in targets:
 if mesh_geometry_hash(o.data)==expected:retained.append({'object':o.name,'key':o['program_key']});continue
 old=o.data;box=extent(old);newbox=extent(native);assert max(abs(box[i][k]-newbox[i][k]) for i in range(2) for k in range(3))<1e-6;assert upper(old)==upper(native);assert len(old.materials)==len(native.materials);mats=list(old.materials);copy=native.copy()
 for i,m in enumerate(mats):copy.materials[i]=m
 matrix=o.matrix_world.copy();o.data=copy;o.matrix_world=matrix;o['native_factory_product']='wc117_support_clearance_trial';o['wc_variant']='integrated_trap_batch122';o['sanitary_product_approved']=False;rows.append({'object':o.name,'key':o['program_key'],'before_faces':len(old.polygons),'after_faces':len(copy.polygons),'local_bounds_unchanged_m':box,'upper_coordinate_set_unchanged':True,'pose_and_scale_unchanged':True,'room_material_slots_preserved':[m.name for m in mats]})
assert len(rows)==8 and len(retained)==2;assert all(mesh_geometry_hash(o.data)==expected for o in targets);bpy.data.objects.remove(proto,do_unlink=True);bpy.ops.wm.save_as_mainfile(filepath=str(dst));assert sha(src)==before;(d/'all_traps122_build.json').write_text(json.dumps({'source':str(src),'source_sha256':before,'candidate':str(dst),'candidate_sha256':sha(dst),'product':str(product),'product_sha256':sha(product),'replaced':rows,'retained_two_tested_core_products':retained,'all_ten_native_derived_geometry_identical':True,'scope':'Eight further native products receive exactly the same routed ceramic geometry as two-room121 test. No product/object scaling, outer extents/upper shape/poses/material slots changed. This extends a visible continuity improvement, NOT final sanitary photo/plumbing approval. All ten room views, physical regressions, dry joint/water detail and full scene/navigation still require review.','accepted':False},indent=2));print('RESIDENTIAL122_ALL_TEN_TRAP_TRIAL_SAVED')
