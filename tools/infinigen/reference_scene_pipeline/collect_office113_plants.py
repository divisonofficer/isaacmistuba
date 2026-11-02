"""Copy three named real small plant products with byte-identical dependencies."""
from pathlib import Path
import json,hashlib,shutil
r=Path(__file__).resolve().parents[3];d=r/'data/venue_refs/floor_plans_v3/commercial_office_floor_02';p=d/'plants113_products';p.mkdir(exist_ok=True);dstroot=r/'assets/opticalnav_curated/office_plants113';assert not dstroot.exists();dstroot.mkdir();wanted=['HSSD_0d3e9c7193817df7a779fb18577d7960bc0dcf04','HSSD_17292deefa4135485bbcbcdbaa366b951ddc7075','HSSD_223af36e92a0aa97bf08833dfb9365c20e3ec240'];sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest();rows=[]
for e in json.loads((d/'plants113_local_candidates.json').read_text())['candidates']:
 if e['id'] not in wanted:continue
 src=Path(e['path']);dst=dstroot/e['id']/src.name;dst.parent.mkdir();shutil.copyfile(src,dst);assert sha(src)==sha(dst);deps=[]
 for category in ['buffers','images']:
  for dep in json.loads(src.read_text()).get(category,[]):
   uri=dep.get('uri','')
   if not uri or uri.startswith('data:'):continue
   rel=Path(uri);assert not rel.is_absolute() and '..' not in rel.parts;target=dst.parent/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src.parent/rel,target);assert sha(src.parent/rel)==sha(target);deps.append({'uri':uri,'sha256':sha(target)})
 rows.append({**e,'path':str(dst.relative_to(r)),'original_path':str(src),'source_sha256':sha(src),'dependencies':deps})
assert len(rows)==3;(p/'asset_manifest.json').write_text(json.dumps({'assets':rows,'scope':'Native products copied locally, no rescaling or visual approval. HSSD inferred material parameters retained, not measured PBR.'},indent=2));print('THREE_NATIVE_PLANTS_COPIED')
