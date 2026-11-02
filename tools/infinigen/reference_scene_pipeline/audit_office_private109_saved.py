"""Reopen saved109, verify five native chair mesh/UV/material instances without photo claims."""
import bpy,json,hashlib
from pathlib import Path
root=Path(__file__).resolve().parents[3];r=root/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';m=json.loads((r/'private_chairs109_build.json').read_text());src=Path(m['source']);dst=Path(m['candidate']);sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();assert sha(src)==m['source_sha256'];assert sha(dst)==m['candidate_sha256'];bpy.ops.wm.open_mainfile(filepath=str(dst));proto=next(o for o in bpy.context.scene.objects if o.get('program_key')=='private_1_chair');rows=[]
for item in m['replacements']:
 o=next(o for o in bpy.context.scene.objects if o.get('program_key')==item['role']);assert o.data==proto.data;assert list(o.data.materials)==list(proto.data.materials);assert all(abs(v-1)<1e-6 for v in o.scale);assert o['original_asset_id']==proto['original_asset_id'];assert not o.children
 assert not any(str(x.get('program_key','')).startswith(item['role']+'_') for x in bpy.context.scene.objects)
 rows.append({'role':item['role'],'same_native_mesh_datablock':True,'same_uv_layers':True,'same_material_bindings':True,'scale':list(o.scale),'vertices':len(o.data.vertices),'polygons':len(o.data.polygons),'legacy_auxiliary_parts_absent':True})
images=[]
for mat in proto.data.materials:
 if mat and mat.use_nodes:
  for n in mat.node_tree.nodes:
   if n.type=='TEX_IMAGE' and n.image:
    assert n.image.packed_file;images.append({'image':n.image.name,'packed_sha256':hashlib.sha256(n.image.packed_file.data).hexdigest()})
(r/'private_chairs109_saved_audit.json').write_text(json.dumps({'pass':True,'source_sha256':m['source_sha256'],'candidate_sha256':m['candidate_sha256'],'chairs':rows,'native_images':images,'scope':'Saved mesh identity includes UVs and material bindings; unit scale, packed images, no legacy auxiliary parts. Build-time surface checks separate. No photorealism, full navigation, support remeasurement or dataset approval.'},indent=2));print('PRIVATE109_SAVED_NATIVE_AUDIT_PASS')
