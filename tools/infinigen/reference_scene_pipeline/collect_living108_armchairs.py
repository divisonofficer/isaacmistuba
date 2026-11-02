"""Copy three native monitor candidates for visual screening, no adoption."""
from pathlib import Path
import json,hashlib,shutil
root=Path(__file__).resolve().parents[3];r=root/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';p=r/'living108_armchair_products';p.mkdir(exist_ok=True);a=root/'assets/opticalnav_curated/residential_living108_armchairs';assert not a.exists();a.mkdir(parents=True)
ids=['HSSD_0df55741b2499a6d155ba54ec55199e85ed83386','HSSD_3aaccfa2eb2d93162748ffc157aa69bae0d4199c'];entries=[];sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
for e in json.loads((r/'living108_armchair_candidates.json').read_text())['candidates']:
 if e['id'] not in ids:continue
 src=Path(e['path']);assert src.suffix=='.gltf';dst=a/e['id']/src.name;dst.parent.mkdir();shutil.copyfile(src,dst);assert sha(src)==sha(dst);deps=[];doc=json.loads(src.read_text())
 for category in ['buffers','images']:
  for dep in doc.get(category,[]):
   uri=dep.get('uri','')
   if not uri or uri.startswith('data:'):continue
   rel=Path(uri);assert not rel.is_absolute() and '..' not in rel.parts;target=dst.parent/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src.parent/rel,target);assert sha(src.parent/rel)==sha(target);deps.append({'uri':uri,'sha256':sha(target)})
 entries.append({**e,'path':str(dst.relative_to(root)),'original_path':str(src),'copied_sha256':sha(dst),'dependencies':deps})
assert len(entries)==2;(p/'asset_manifest.json').write_text(json.dumps({'assets':entries,'scope':'Original product geometry and material data, byte-identical local copies. Native size; no visual approval or scene integration.'},indent=2));print('LIVING108_TWO_ARMCHAIRS_COPIED')
