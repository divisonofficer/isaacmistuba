"""Saved107 native table identity verification, separate from visual acceptance."""
import bpy,json,hashlib,struct
from pathlib import Path
root=Path(__file__).resolve().parents[3];r=root/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';meta=json.loads((r/'living107_tables_build.json').read_text());dst=Path(meta['candidate']);sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();assert sha(dst)==meta['candidate_sha256'];bpy.ops.wm.open_mainfile(filepath=str(dst));rows=[]
def fingerprint(o):
 h=hashlib.sha256()
 for v in o.data.vertices:h.update(struct.pack('fff',*v.co))
 for f in o.data.polygons:h.update(struct.pack('I',len(f.vertices)));h.update(struct.pack('I'*len(f.vertices),*f.vertices));h.update(struct.pack('I',f.material_index))
 for layer in o.data.uv_layers:
  for uv in layer.data:h.update(struct.pack('ff',*uv.uv))
 return h.hexdigest()
for item in meta['tables']:
 names=tuple(item['native_parts']);actual={name:bpy.context.scene.objects[name] for name in names};assert all(o.get('original_asset_id')==item['asset'] for o in actual.values())
 before={name:fingerprint(o) for name,o in actual.items()}
 with bpy.data.libraries.load(str(r/'living107_table_products/review_studio.blend'),link=False) as (a,z):z.objects=list(names)
 for name,original in zip(names,z.objects):
  assert original and fingerprint(original)==before[name];o=actual[name];assert all(abs(x-1)<1e-5 for x in o.scale);assert len(o.data.materials)==len(original.data.materials)
  rows.append({'unit':item['unit'],'object':name,'native_geometry_uv_material_indices_identical':True,'scale':list(o.scale),'mesh_sha256':before[name]})
(r/'living107_saved_audit.json').write_text(json.dumps({'pass':True,'candidate_sha256':meta['candidate_sha256'],'native_components':rows,'scope':'Saved native vertices/topology/material indices/UV exact identity and unit scale. Material node graph, support, collision and photo quality are separate checks.'},indent=2));print('LIVING107_SAVED_NATIVE_AUDIT_PASS')
