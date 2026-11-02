"""Copy three named real small plant products with byte-identical dependencies."""
from pathlib import Path
import json,hashlib,shutil
r=Path(__file__).resolve().parents[3];d=r/'data/venue_refs/floor_plans_v3/dual_unit_residential_floor_03';p=d/'bedroom110_products';p.mkdir(exist_ok=True);dstroot=r/'assets/opticalnav_curated/residential_bedroom110';assert not dstroot.exists();dstroot.mkdir();wanted=['HSSD_ccb76c83b981fc6f627b66ba20f3013ab866c47f','HSSD_xxxx2d7fa89ax71d3x4ac7xb350xa294dd8ef99b'];sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();rows=[]
for e in json.loads((d/'bedroom110_nightstand_candidates.json').read_text())['candidates']:
 if e['id'] not in wanted:continue
 src=Path(e['path']);dst=dstroot/e['id']/src.name;dst.parent.mkdir();shutil.copyfile(src,dst);assert sha(src)==sha(dst);deps=[]
 for category in ['buffers','images']:
  for dep in json.loads(src.read_text()).get(category,[]):
   uri=dep.get('uri','')
   if not uri or uri.startswith('data:'):continue
   rel=Path(uri);assert not rel.is_absolute() and '..' not in rel.parts;target=dst.parent/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src.parent/rel,target);assert sha(src.parent/rel)==sha(target);deps.append({'uri':uri,'sha256':sha(target)})
 rows.append({**e,'path':str(dst.relative_to(r)),'original_path':str(src),'source_sha256':sha(src),'dependencies':deps})
assert len(rows)==2;(p/'asset_manifest.json').write_text(json.dumps({'assets':rows,'scope':'Native products copied locally, no rescaling or visual approval. HSSD inferred material parameters retained, not measured PBR.'},indent=2));print('TWO_NATIVE_NIGHTSTANDS_COPIED')
