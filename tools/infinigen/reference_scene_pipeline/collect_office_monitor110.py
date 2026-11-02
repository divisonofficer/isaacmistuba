"""Copy three native monitor candidates for visual screening, no adoption."""
from pathlib import Path
import json,hashlib,shutil
root=Path(__file__).resolve().parents[3];r=root/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';p=r/'native_monitor110_products';p.mkdir(exist_ok=True);a=root/'assets/opticalnav_curated/office_monitor110';assert not a.exists();a.mkdir(parents=True)
ids=['HSSD_2029bfb9eca4ab612eb6724916cbff472de47d7b','HSSD_ad9fc592f9942a7e3feaa19a697329bd65bb7ed3','HSSD_878fded4b4bc0dcec55d68a662a89ab81c8f0cd5'];entries=[];sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
for e in json.loads((r/'native_monitor110_candidates.json').read_text())['candidates']:
 if e['id'] not in ids:continue
 src=Path(e['path']);assert src.suffix=='.gltf';dst=a/e['id']/src.name;dst.parent.mkdir();shutil.copyfile(src,dst);assert sha(src)==sha(dst);deps=[];doc=json.loads(src.read_text())
 for category in ['buffers','images']:
  for dep in doc.get(category,[]):
   uri=dep.get('uri','')
   if not uri or uri.startswith('data:'):continue
   rel=Path(uri);assert not rel.is_absolute() and '..' not in rel.parts;target=dst.parent/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src.parent/rel,target);assert sha(src.parent/rel)==sha(target);deps.append({'uri':uri,'sha256':sha(target)})
 entries.append({**e,'path':str(dst.relative_to(root)),'original_path':str(src),'copied_sha256':sha(dst),'dependencies':deps})
assert len(entries)==3;(p/'asset_manifest.json').write_text(json.dumps({'assets':entries,'scope':'Original product geometry and material data, byte-identical local copies. Native size; no visual approval or scene integration.'},indent=2));print('MONITOR110_THREE_COPIED')
